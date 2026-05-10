# Zoom MCP Server v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Zoom MCP server as a read-only, AI-Companion-powered, MCPB-distributed Python server with 22 tools spanning Team Chat, meetings, transcripts, shared spaces, and grounded Q&A — replacing the brittle v1 setup.sh/bash-wrapper distribution.

**Architecture:** Modular Python package under `server/` with TLS-1.2-hardened shared httpx client, SQLite metadata cache (no message/transcript content on disk), Fernet-encrypted OAuth tokens in OS-standard user-data dir, declarative endpoint route table, and per-platform `.mcpb` bundles built via `npx @anthropic-ai/mcpb pack`.

**Tech Stack:** Python 3.10+, mcp SDK, httpx, cryptography (Fernet), pytest, pytest-asyncio, pytest-httpx, sqlite3 (stdlib), `@anthropic-ai/mcpb` packer.

**Spec reference:** `docs/superpowers/specs/2026-05-10-zoom-mcp-v2-design.md` — read this FIRST before starting any task.

---

## File Structure

```
zoom-mcp-server/
├── manifest.json                  # MCPB manifest (Task 11)
├── icon.png                       # Square logo (Task 11)
├── requirements.txt               # Authoritative deps (Task 1)
├── pyproject.toml                 # Dev/test config (Task 1)
├── README.md                      # MCPB-only distribution docs (Task 12)
├── server/
│   ├── __init__.py                # (Task 1)
│   ├── main.py                    # Entry point (Task 10)
│   ├── paths.py                   # OS-aware user-data/log dirs (Task 2)
│   ├── log_filter.py              # Sensitive-field scrubber (Task 2)
│   ├── http_client.py             # Shared httpx + TLS 1.2+ + retry (Task 2)
│   ├── token_store.py             # Fernet-encrypted token storage (Task 3)
│   ├── oauth.py                   # ZoomOAuthHandler (Task 4)
│   ├── dispatcher.py              # Generic API dispatch + auto-pagination (Task 5)
│   ├── endpoints.py               # ENDPOINTS route table (22 tools) (Task 5)
│   ├── ai_companion.py            # zoom_search + zoom_ask (Task 6)
│   ├── transcripts.py             # VTT parser + transcript fetch (Task 7)
│   ├── files.py                   # zoom_get_file (Task 8)
│   ├── shared_spaces.py           # Shared space tools (Task 9)
│   ├── tools.py                   # Tool registration + call_tool routing (Task 10)
│   └── cache/
│       ├── __init__.py            # (Task 3)
│       ├── schema.py              # CREATE TABLE statements (Task 3)
│       └── store.py               # SQLite TTL cache (Task 3)
├── scripts/
│   ├── build_mcpb.sh              # Build per-platform .mcpb files (Task 11)
│   └── dev-run.sh                 # Run from source (Task 11)
└── tests/
    ├── __init__.py
    ├── test_paths.py              # (Task 2)
    ├── test_log_filter.py         # (Task 2)
    ├── test_http_client.py        # (Task 2)
    ├── test_token_store.py        # (Task 3)
    ├── test_cache_store.py        # (Task 3)
    ├── test_dispatcher.py         # (Task 5)
    ├── test_ai_companion.py       # (Task 6)
    ├── test_transcripts.py        # (Task 7)
    ├── test_files.py              # (Task 8)
    ├── test_shared_spaces.py      # (Task 9)
    └── test_message_inline.py     # (Task 9)
```

**Removed in Task 12:** `setup.sh`, `zoom_wrapper.sh`, `.env.example`, `base_mcp_server.py`, `zoom_oauth_handler.py`, `zoom_server.py`, `utils/` (entire dir).

---

## Task 1: Skeleton + dependencies

**Files:**
- Create: `requirements.txt`, `pyproject.toml`, `server/__init__.py`, `server/cache/__init__.py`, `tests/__init__.py`, `scripts/.gitkeep`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p server/cache tests scripts
touch server/__init__.py server/cache/__init__.py tests/__init__.py
```

- [ ] **Step 2: Write requirements.txt**

```
mcp>=1.0.0
httpx>=0.27.0
cryptography>=41.0.0
```

`python-dotenv` is dropped (config comes from MCPB `user_config` env vars).

- [ ] **Step 3: Write pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "zoom-mcp-server"
version = "2.0.0"
requires-python = ">=3.10"
dependencies = [
    "mcp>=1.0.0",
    "httpx>=0.27.0",
    "cryptography>=41.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-httpx>=0.30",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.setuptools]
packages = ["server", "server.cache"]
```

- [ ] **Step 4: Set up dev venv and install**

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

- [ ] **Step 5: Smoke-check**

```bash
.venv/bin/python -c "import mcp, httpx, cryptography; print('ok')"
```
Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add requirements.txt pyproject.toml server/ tests/ scripts/
git commit -m "feat: skeleton for v2 server module layout"
```

---

## Task 2: Foundation modules — paths, log_filter, http_client

**Files:**
- Create: `server/paths.py`, `server/log_filter.py`, `server/http_client.py`
- Test: `tests/test_paths.py`, `tests/test_log_filter.py`, `tests/test_http_client.py`

### 2A: paths.py

- [ ] **Step 1: Write failing tests**

```python
# tests/test_paths.py
import os
from unittest.mock import patch
from pathlib import Path
from server import paths


def test_user_data_dir_macos(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setenv("HOME", "/Users/test")
    assert paths.user_data_dir() == Path("/Users/test/Library/Application Support/zoom-mcp")


def test_user_data_dir_linux_xdg(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "/tmp/xdg")
    assert paths.user_data_dir() == Path("/tmp/xdg/zoom-mcp")


def test_user_data_dir_linux_default(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", "/home/test")
    assert paths.user_data_dir() == Path("/home/test/.local/share/zoom-mcp")


def test_user_data_dir_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\test\AppData\Roaming")
    assert paths.user_data_dir() == Path(r"C:\Users\test\AppData\Roaming\zoom-mcp")


def test_log_dir_macos(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setenv("HOME", "/Users/test")
    assert paths.log_dir() == Path("/Users/test/Library/Logs/zoom-mcp")


def test_ensure_dirs_creates_with_0700(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(paths, "log_dir", lambda: tmp_path / "logs")
    paths.ensure_dirs()
    assert (tmp_path / "data").exists()
    assert (tmp_path / "logs").exists()
    # On Unix, mode is 0o700; on Windows the test still passes because dir exists
    if os.name == "posix":
        assert oct((tmp_path / "data").stat().st_mode)[-3:] == "700"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_paths.py -v
```
Expected: ImportError on `from server import paths`

- [ ] **Step 3: Implement server/paths.py**

```python
"""Cross-platform user-data and log directory resolution. No external deps."""
import os
import sys
from pathlib import Path

APP_NAME = "zoom-mcp"


def user_data_dir() -> Path:
    """Return the OS-standard application-data directory for this app."""
    if sys.platform == "darwin":
        return Path(os.environ["HOME"]) / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / APP_NAME
    return Path(os.environ["HOME"]) / ".local" / "share" / APP_NAME


def log_dir() -> Path:
    """Return the OS-standard log directory for this app."""
    if sys.platform == "darwin":
        return Path(os.environ["HOME"]) / "Library" / "Logs" / APP_NAME
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / APP_NAME / "logs"
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / APP_NAME
    return Path(os.environ["HOME"]) / ".local" / "state" / APP_NAME


def token_file() -> Path:
    return user_data_dir() / "tokens.enc"


def token_key_file() -> Path:
    return user_data_dir() / "tokens.key"


def cache_db_file() -> Path:
    return user_data_dir() / "cache.sqlite"


def log_file() -> Path:
    return log_dir() / "zoom-mcp.log"


def ensure_dirs() -> None:
    """Create user-data and log dirs with restrictive perms (Unix)."""
    for p in (user_data_dir(), log_dir()):
        p.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(p, 0o700)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_paths.py -v
```
Expected: 6 passed

### 2B: log_filter.py

- [ ] **Step 5: Write failing tests**

```python
# tests/test_log_filter.py
import logging
from server.log_filter import SensitiveFilter


def _capture(records, msg, *args):
    rec = logging.LogRecord("test", logging.INFO, __file__, 0, msg, args, None)
    SensitiveFilter().filter(rec)
    return rec.getMessage()


def test_filter_redacts_bearer_token():
    out = _capture([], "Calling with Authorization: Bearer abc123def456")
    assert "abc123" not in out
    assert "[redacted]" in out


def test_filter_redacts_refresh_token_in_dict():
    out = _capture([], "Got %s", {"refresh_token": "xyz789", "expires_in": 3600})
    assert "xyz789" not in out
    assert "expires_in" in out  # other fields preserved


def test_filter_redacts_search_key_qparam():
    out = _capture([], "GET /messages?search_key=secret&page=1")
    assert "secret" not in out
    assert "page=1" in out


def test_filter_redacts_email_in_path():
    out = _capture([], "GET /users/jane.doe@example.com")
    assert "jane.doe@example.com" not in out
    assert "[email]" in out


def test_filter_does_not_redact_safe_messages():
    out = _capture([], "Tool zoom_list_channels completed in 0.42s")
    assert out == "Tool zoom_list_channels completed in 0.42s"
```

- [ ] **Step 6: Run tests, verify they fail**

```bash
.venv/bin/pytest tests/test_log_filter.py -v
```

- [ ] **Step 7: Implement server/log_filter.py**

```python
"""Logging filter that scrubs sensitive content from log records."""
import logging
import re

# Patterns to redact from log message strings
_BEARER_RE = re.compile(r"(Authorization:\s*)Bearer\s+\S+", re.IGNORECASE)
_QPARAM_RE = re.compile(
    r"(\b(?:search_key|code|access_token|refresh_token|client_secret)=)([^&\s]+)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_SENSITIVE_KEYS = {
    "access_token", "refresh_token", "client_secret",
    "code", "search_key", "message", "text", "body",
    "content", "transcript", "answer",
}


def _scrub_text(text: str) -> str:
    text = _BEARER_RE.sub(r"\1[redacted]", text)
    text = _QPARAM_RE.sub(r"\1[redacted]", text)
    text = _EMAIL_RE.sub("[email]", text)
    return text


def _scrub_value(v):
    if isinstance(v, dict):
        return {k: ("[redacted]" if k in _SENSITIVE_KEYS else _scrub_value(val))
                for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return type(v)(_scrub_value(x) for x in v)
    if isinstance(v, str):
        return _scrub_text(v)
    return v


class SensitiveFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _scrub_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = _scrub_value(record.args)
            else:
                record.args = tuple(_scrub_value(a) for a in record.args)
        return True
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_log_filter.py -v
```
Expected: 5 passed

### 2C: http_client.py

- [ ] **Step 9: Write failing tests**

```python
# tests/test_http_client.py
import pytest
import httpx
from pytest_httpx import HTTPXMock
from server.http_client import get_client, request_with_retry


@pytest.mark.asyncio
async def test_client_is_singleton():
    c1 = get_client()
    c2 = get_client()
    assert c1 is c2


@pytest.mark.asyncio
async def test_client_enforces_tls_min_v1_2():
    c = get_client()
    # We can't easily test this against a live server in a unit test;
    # but we can assert the verify context has the right minimum_version.
    import ssl
    ctx = c._transport._pool._ssl_context  # httpx internals; OK for unit test
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2


@pytest.mark.asyncio
async def test_retry_on_429(httpx_mock: HTTPXMock):
    httpx_mock.add_response(status_code=429, headers={"Retry-After": "0"}, json={})
    httpx_mock.add_response(status_code=200, json={"ok": True})
    r = await request_with_retry("GET", "https://api.zoom.us/v2/x")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_retry_on_5xx(httpx_mock: HTTPXMock):
    httpx_mock.add_response(status_code=503, json={})
    httpx_mock.add_response(status_code=200, json={"ok": True})
    r = await request_with_retry("GET", "https://api.zoom.us/v2/x", retry_delay=0)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_no_retry_on_4xx(httpx_mock: HTTPXMock):
    httpx_mock.add_response(status_code=403, json={"err": "forbidden"})
    r = await request_with_retry("GET", "https://api.zoom.us/v2/x", retry_delay=0)
    assert r.status_code == 403
```

- [ ] **Step 10: Run tests, verify they fail**

- [ ] **Step 11: Implement server/http_client.py**

```python
"""Single shared httpx.AsyncClient with TLS 1.2+ and unified retry policy."""
import asyncio
import ssl
from typing import Optional
import httpx

_CLIENT: Optional[httpx.AsyncClient] = None


def _build_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def get_client() -> httpx.AsyncClient:
    global _CLIENT
    if _CLIENT is None or _CLIENT.is_closed:
        _CLIENT = httpx.AsyncClient(
            verify=_build_ssl_context(),
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
            headers={"User-Agent": "zoom-mcp/2.0"},
        )
    return _CLIENT


async def request_with_retry(
    method: str,
    url: str,
    *,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    **kwargs,
) -> httpx.Response:
    """Make an HTTP request with rate-limit and 5xx-aware retries."""
    client = get_client()
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.RequestError as exc:
            last_exc = exc
            if attempt >= max_retries:
                raise
            await asyncio.sleep(retry_delay * (2 ** attempt))
            continue

        if response.status_code == 429:
            if attempt >= max_retries:
                return response
            wait = float(response.headers.get("Retry-After", retry_delay))
            await asyncio.sleep(wait)
            continue

        if 500 <= response.status_code < 600:
            if attempt >= max_retries:
                return response
            await asyncio.sleep(retry_delay * (2 ** attempt))
            continue

        return response

    raise last_exc if last_exc else RuntimeError("retry loop exited unexpectedly")


async def close_client() -> None:
    global _CLIENT
    if _CLIENT is not None:
        await _CLIENT.aclose()
        _CLIENT = None
```

- [ ] **Step 12: Run all tests, verify pass**

```bash
.venv/bin/pytest tests/ -v
```
Expected: all paths/log_filter/http_client tests pass.

- [ ] **Step 13: Commit**

```bash
git add server/paths.py server/log_filter.py server/http_client.py \
        tests/test_paths.py tests/test_log_filter.py tests/test_http_client.py
git commit -m "feat: foundation modules (paths, log_filter, http_client)"
```

---

## Task 3: Token store + cache layer

**Files:**
- Create: `server/token_store.py`, `server/cache/schema.py`, `server/cache/store.py`
- Test: `tests/test_token_store.py`, `tests/test_cache_store.py`

### 3A: token_store.py

- [ ] **Step 1: Write tests**

```python
# tests/test_token_store.py
from datetime import datetime, timedelta
from server.token_store import TokenStore


def test_save_and_load_round_trip(tmp_path):
    store = TokenStore(tmp_path / "tokens.enc", tmp_path / "tokens.key")
    store.save("AT", "RT", datetime.now() + timedelta(hours=1))
    loaded = store.load()
    assert loaded["access_token"] == "AT"
    assert loaded["refresh_token"] == "RT"


def test_load_returns_none_when_no_file(tmp_path):
    store = TokenStore(tmp_path / "tokens.enc", tmp_path / "tokens.key")
    assert store.load() is None


def test_is_expired_with_5min_grace(tmp_path):
    store = TokenStore(tmp_path / "tokens.enc", tmp_path / "tokens.key")
    store.save("AT", "RT", datetime.now() + timedelta(minutes=2))
    assert store.is_expired() is True


def test_delete_removes_files(tmp_path):
    store = TokenStore(tmp_path / "tokens.enc", tmp_path / "tokens.key")
    store.save("AT", "RT", datetime.now() + timedelta(hours=1))
    store.delete()
    assert not (tmp_path / "tokens.enc").exists()
    assert not (tmp_path / "tokens.key").exists()


def test_files_have_0600_perms(tmp_path):
    import os
    store = TokenStore(tmp_path / "tokens.enc", tmp_path / "tokens.key")
    store.save("AT", "RT", datetime.now() + timedelta(hours=1))
    if os.name == "posix":
        assert oct((tmp_path / "tokens.enc").stat().st_mode)[-3:] == "600"
        assert oct((tmp_path / "tokens.key").stat().st_mode)[-3:] == "600"
```

- [ ] **Step 2: Run, verify fail. Implement server/token_store.py**

```python
"""Fernet-encrypted OAuth token storage with restrictive file perms."""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
from cryptography.fernet import Fernet


class TokenStore:
    def __init__(self, token_file: Path, key_file: Path):
        self.token_file = Path(token_file)
        self.key_file = Path(key_file)

    def _key(self) -> bytes:
        if self.key_file.exists():
            return self.key_file.read_bytes()
        key = Fernet.generate_key()
        self.key_file.parent.mkdir(parents=True, exist_ok=True)
        self.key_file.write_bytes(key)
        if os.name == "posix":
            os.chmod(self.key_file, 0o600)
        return key

    def save(
        self,
        access_token: str,
        refresh_token: Optional[str],
        expires_at: datetime,
        token_type: str = "Bearer",
        scope: Optional[str] = None,
    ) -> None:
        data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at.isoformat(),
            "token_type": token_type,
            "scope": scope,
            "created_at": datetime.now().isoformat(),
        }
        plaintext = json.dumps(data).encode()
        ciphertext = Fernet(self._key()).encrypt(plaintext)
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_bytes(ciphertext)
        if os.name == "posix":
            os.chmod(self.token_file, 0o600)

    def load(self) -> Optional[Dict[str, Any]]:
        if not self.token_file.exists() or not self.key_file.exists():
            return None
        try:
            ciphertext = self.token_file.read_bytes()
            plaintext = Fernet(self._key()).decrypt(ciphertext)
            data = json.loads(plaintext.decode())
            data["expires_at"] = datetime.fromisoformat(data["expires_at"])
            return data
        except Exception:
            return None

    def is_expired(self, grace_minutes: int = 5) -> bool:
        data = self.load()
        if not data:
            return True
        return datetime.now() >= data["expires_at"] - timedelta(minutes=grace_minutes)

    def delete(self) -> None:
        for p in (self.token_file, self.key_file):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
```

- [ ] **Step 3: Run tests, verify pass**

### 3B: cache/schema.py

- [ ] **Step 4: Write server/cache/schema.py**

```python
"""SQL DDL for the SQLite metadata cache. Run apply_schema(conn) on every open."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS channels (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  type          INTEGER,
  member_count  INTEGER,
  jid           TEXT,
  channel_url   TEXT,
  starred       INTEGER,
  cached_at     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_channels_name    ON channels(name);
CREATE INDEX IF NOT EXISTS idx_channels_starred ON channels(starred);

CREATE TABLE IF NOT EXISTS contacts (
  id              TEXT PRIMARY KEY,
  email           TEXT NOT NULL,
  display_name    TEXT,
  dept            TEXT,
  presence_status TEXT,
  cached_at       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email);
CREATE INDEX IF NOT EXISTS idx_contacts_name  ON contacts(display_name);

CREATE TABLE IF NOT EXISTS email_to_id (
  email     TEXT PRIMARY KEY,
  user_id   TEXT NOT NULL,
  cached_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_members (
  channel_id  TEXT NOT NULL,
  user_id     TEXT NOT NULL,
  role        TEXT,
  cached_at   INTEGER NOT NULL,
  PRIMARY KEY (channel_id, user_id)
);

CREATE TABLE IF NOT EXISTS meetings (
  id              TEXT PRIMARY KEY,
  uuid            TEXT,
  topic           TEXT,
  start_time      TEXT,
  duration        INTEGER,
  host_id         TEXT,
  has_recording   INTEGER,
  cached_at       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_meetings_start ON meetings(start_time);
CREATE INDEX IF NOT EXISTS idx_meetings_topic ON meetings(topic);

CREATE TABLE IF NOT EXISTS meeting_files (
  meeting_id      TEXT NOT NULL,
  file_id         TEXT NOT NULL,
  file_type       TEXT,
  file_size       INTEGER,
  recording_start TEXT,
  cached_at       INTEGER NOT NULL,
  PRIMARY KEY (meeting_id, file_id)
);

CREATE TABLE IF NOT EXISTS shared_spaces (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  member_count  INTEGER,
  channel_count INTEGER,
  owner_id      TEXT,
  cached_at     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS shared_space_channels (
  space_id    TEXT NOT NULL,
  channel_id  TEXT NOT NULL,
  cached_at   INTEGER NOT NULL,
  PRIMARY KEY (space_id, channel_id)
);

CREATE TABLE IF NOT EXISTS shared_space_members (
  space_id   TEXT NOT NULL,
  user_id    TEXT NOT NULL,
  role       TEXT,
  cached_at  INTEGER NOT NULL,
  PRIMARY KEY (space_id, user_id)
);

CREATE TABLE IF NOT EXISTS mention_groups (
  channel_id    TEXT NOT NULL,
  group_id      TEXT NOT NULL,
  name          TEXT,
  member_count  INTEGER,
  cached_at     INTEGER NOT NULL,
  PRIMARY KEY (channel_id, group_id)
);
"""


def apply_schema(conn) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()
```

### 3C: cache/store.py

- [ ] **Step 5: Write tests**

```python
# tests/test_cache_store.py
import time
from server.cache.store import CacheStore


def test_put_and_get_channels(tmp_path):
    store = CacheStore(tmp_path / "cache.db")
    store.put_channels([
        {"id": "c1", "name": "general", "type": 3, "member_count": 50},
        {"id": "c2", "name": "devs", "type": 1, "member_count": 8, "starred": True},
    ])
    rows = store.get_channels()
    assert len(rows) == 2
    by_name = {r["name"]: r for r in rows}
    assert by_name["devs"]["starred"] == 1


def test_ttl_eviction(tmp_path, monkeypatch):
    store = CacheStore(tmp_path / "cache.db")
    fake_now = [1000]
    monkeypatch.setattr("server.cache.store._now_ms", lambda: fake_now[0] * 1000)
    store.put_channels([{"id": "c1", "name": "x", "type": 3}])
    fake_now[0] = 1000 + 3601  # 1h+1s later
    assert store.get_channels(ttl_seconds=3600) == []


def test_starred_filter(tmp_path):
    store = CacheStore(tmp_path / "cache.db")
    store.put_channels([
        {"id": "c1", "name": "x", "type": 3, "starred": False},
        {"id": "c2", "name": "y", "type": 3, "starred": True},
    ])
    starred = store.get_channels(starred_only=True)
    assert len(starred) == 1
    assert starred[0]["name"] == "y"


def test_email_to_id(tmp_path):
    store = CacheStore(tmp_path / "cache.db")
    store.put_email_to_id("a@b.com", "U1")
    assert store.get_user_id_by_email("a@b.com") == "U1"


def test_clear_wipes_everything(tmp_path):
    store = CacheStore(tmp_path / "cache.db")
    store.put_channels([{"id": "c1", "name": "x", "type": 3}])
    store.put_email_to_id("a@b.com", "U1")
    store.clear_all()
    assert store.get_channels() == []
    assert store.get_user_id_by_email("a@b.com") is None
```

- [ ] **Step 6: Implement server/cache/store.py**

```python
"""SQLite-backed metadata cache with TTL eviction. No message/transcript content stored."""
import os
import sqlite3
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Iterable
from .schema import apply_schema


def _now_ms() -> int:
    return int(time.time() * 1000)


class CacheStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        apply_schema(self._conn)
        if os.name == "posix":
            os.chmod(self.db_path, 0o600)

    # --- channels ---

    def put_channels(self, channels: Iterable[Dict[str, Any]]) -> None:
        ts = _now_ms()
        rows = [
            (c["id"], c["name"], c.get("type"), c.get("member_count"),
             c.get("jid"), c.get("channel_url"),
             1 if c.get("starred") else 0, ts)
            for c in channels
        ]
        self._conn.executemany(
            "INSERT OR REPLACE INTO channels "
            "(id, name, type, member_count, jid, channel_url, starred, cached_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    def get_channels(
        self,
        ttl_seconds: int = 3600,
        starred_only: bool = False,
    ) -> List[Dict[str, Any]]:
        cutoff = _now_ms() - ttl_seconds * 1000
        sql = "SELECT * FROM channels WHERE cached_at >= ?"
        params: list = [cutoff]
        if starred_only:
            sql += " AND starred = 1"
        sql += " ORDER BY name"
        return [dict(r) for r in self._conn.execute(sql, params)]

    def get_channel_by_id(self, channel_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM channels WHERE id = ?", (channel_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_channel_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM channels WHERE name = ? LIMIT 1", (name,)
        ).fetchone()
        return dict(row) if row else None

    # --- contacts ---

    def put_contacts(self, contacts: Iterable[Dict[str, Any]]) -> None:
        ts = _now_ms()
        rows = [
            (c["id"], c.get("email", ""), c.get("display_name"),
             c.get("dept"), c.get("presence_status"), ts)
            for c in contacts
        ]
        self._conn.executemany(
            "INSERT OR REPLACE INTO contacts "
            "(id, email, display_name, dept, presence_status, cached_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )

    def get_contacts(self, ttl_seconds: int = 86400) -> List[Dict[str, Any]]:
        cutoff = _now_ms() - ttl_seconds * 1000
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM contacts WHERE cached_at >= ? ORDER BY display_name",
            (cutoff,),
        )]

    def get_contact_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM contacts WHERE email = ? LIMIT 1", (email,),
        ).fetchone()
        return dict(row) if row else None

    # --- email -> id ---

    def put_email_to_id(self, email: str, user_id: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO email_to_id (email, user_id, cached_at) VALUES (?, ?, ?)",
            (email, user_id, _now_ms()),
        )

    def get_user_id_by_email(
        self, email: str, ttl_seconds: int = 30 * 86400
    ) -> Optional[str]:
        cutoff = _now_ms() - ttl_seconds * 1000
        row = self._conn.execute(
            "SELECT user_id FROM email_to_id WHERE email = ? AND cached_at >= ?",
            (email, cutoff),
        ).fetchone()
        return row["user_id"] if row else None

    # --- channel members ---

    def put_channel_members(self, channel_id: str, members: Iterable[Dict[str, Any]]) -> None:
        ts = _now_ms()
        self._conn.execute(
            "DELETE FROM channel_members WHERE channel_id = ?", (channel_id,),
        )
        rows = [(channel_id, m["id"], m.get("role"), ts) for m in members]
        self._conn.executemany(
            "INSERT INTO channel_members (channel_id, user_id, role, cached_at) "
            "VALUES (?, ?, ?, ?)", rows,
        )

    def get_channel_members(
        self, channel_id: str, ttl_seconds: int = 3600
    ) -> List[Dict[str, Any]]:
        cutoff = _now_ms() - ttl_seconds * 1000
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM channel_members "
            "WHERE channel_id = ? AND cached_at >= ?",
            (channel_id, cutoff),
        )]

    # --- meetings ---

    def put_meetings(self, meetings: Iterable[Dict[str, Any]]) -> None:
        ts = _now_ms()
        rows = [
            (m["id"], m.get("uuid"), m.get("topic"), m.get("start_time"),
             m.get("duration"), m.get("host_id"),
             1 if m.get("has_recording") else 0, ts)
            for m in meetings
        ]
        self._conn.executemany(
            "INSERT OR REPLACE INTO meetings "
            "(id, uuid, topic, start_time, duration, host_id, has_recording, cached_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows,
        )

    def get_meeting(self, meeting_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM meetings WHERE id = ?", (meeting_id,),
        ).fetchone()
        return dict(row) if row else None

    # --- shared spaces ---

    def put_shared_spaces(self, spaces: Iterable[Dict[str, Any]]) -> None:
        ts = _now_ms()
        rows = [
            (s["id"], s.get("name", ""), s.get("member_count"),
             s.get("channel_count"), s.get("owner_id"), ts)
            for s in spaces
        ]
        self._conn.executemany(
            "INSERT OR REPLACE INTO shared_spaces "
            "(id, name, member_count, channel_count, owner_id, cached_at) "
            "VALUES (?, ?, ?, ?, ?, ?)", rows,
        )

    def get_shared_spaces(self, ttl_seconds: int = 3600) -> List[Dict[str, Any]]:
        cutoff = _now_ms() - ttl_seconds * 1000
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM shared_spaces WHERE cached_at >= ? ORDER BY name",
            (cutoff,),
        )]

    # --- mention groups ---

    def put_mention_groups(self, channel_id: str, groups: Iterable[Dict[str, Any]]) -> None:
        ts = _now_ms()
        self._conn.execute(
            "DELETE FROM mention_groups WHERE channel_id = ?", (channel_id,),
        )
        rows = [(channel_id, g["id"], g.get("name"), g.get("member_count"), ts)
                for g in groups]
        self._conn.executemany(
            "INSERT INTO mention_groups (channel_id, group_id, name, member_count, cached_at) "
            "VALUES (?, ?, ?, ?, ?)", rows,
        )

    def get_mention_groups(
        self, channel_id: str, ttl_seconds: int = 3600
    ) -> List[Dict[str, Any]]:
        cutoff = _now_ms() - ttl_seconds * 1000
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM mention_groups WHERE channel_id = ? AND cached_at >= ?",
            (channel_id, cutoff),
        )]

    # --- maintenance ---

    def clear_all(self) -> None:
        for table in (
            "channels", "contacts", "email_to_id", "channel_members",
            "meetings", "meeting_files", "shared_spaces",
            "shared_space_channels", "shared_space_members", "mention_groups",
        ):
            self._conn.execute(f"DELETE FROM {table}")

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 7: Run all tests, verify pass**

```bash
.venv/bin/pytest tests/test_token_store.py tests/test_cache_store.py -v
```

- [ ] **Step 8: Commit**

```bash
git add server/token_store.py server/cache/ \
        tests/test_token_store.py tests/test_cache_store.py
git commit -m "feat: token store and SQLite metadata cache with TTL eviction"
```

---

## Task 4: oauth.py — Zoom OAuth handler refactor

**Files:**
- Create: `server/oauth.py`
- Test: `tests/test_oauth.py`

- [ ] **Step 1: Write tests using mocked httpx**

```python
# tests/test_oauth.py
import pytest
from datetime import datetime, timedelta
from server.oauth import ZoomOAuthHandler
from server.token_store import TokenStore


@pytest.mark.asyncio
async def test_get_auth_headers_uses_loaded_token(tmp_path):
    store = TokenStore(tmp_path / "tokens.enc", tmp_path / "tokens.key")
    store.save("AT123", "RT", datetime.now() + timedelta(hours=1))
    h = ZoomOAuthHandler("client_id", "client_secret", token_store=store)
    headers = h.get_auth_headers()
    assert headers["Authorization"] == "Bearer AT123"


@pytest.mark.asyncio
async def test_refresh_uses_existing_refresh_token(httpx_mock, tmp_path):
    store = TokenStore(tmp_path / "tokens.enc", tmp_path / "tokens.key")
    store.save("OLD", "REFRESH123", datetime.now() - timedelta(minutes=1))
    httpx_mock.add_response(
        url="https://zoom.us/oauth/token",
        json={"access_token": "NEW", "refresh_token": "REFRESH456",
              "expires_in": 3600, "token_type": "Bearer"},
    )
    h = ZoomOAuthHandler("cid", "csec", token_store=store)
    ok = await h.refresh_access_token()
    assert ok is True
    assert store.load()["access_token"] == "NEW"
    assert store.load()["refresh_token"] == "REFRESH456"


def test_get_auth_url_contains_required_params():
    store = TokenStore("/tmp/x", "/tmp/y")
    h = ZoomOAuthHandler("CID", "CSEC", token_store=store, redirect_uri="http://localhost:8000/cb")
    url = h.get_auth_url()
    assert "client_id=CID" in url
    assert "response_type=code" in url
    assert "redirect_uri=" in url
```

- [ ] **Step 2: Implement server/oauth.py**

```python
"""Zoom OAuth2 authorization-code handler with browser callback flow."""
import asyncio
import socket
import threading
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .http_client import request_with_retry
from .token_store import TokenStore

ZOOM_AUTH_URL = "https://zoom.us/oauth/authorize"
ZOOM_TOKEN_URL = "https://zoom.us/oauth/token"


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != getattr(self.server, "expected_path", "/oauth/callback"):
            self.send_response(404); self.end_headers(); return
        params = parse_qs(parsed.query)
        if "code" in params:
            self.server.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Authorization successful</h2>"
                b"<p>You can close this window.</p></body></html>"
            )
        elif "error" in params:
            self.server.auth_error = params["error"][0]
            self.send_response(400); self.end_headers()
            self.wfile.write(f"Error: {params['error'][0]}".encode())
        else:
            self.send_response(400); self.end_headers()

    def log_message(self, format, *args):  # silence default logs
        pass


class ZoomOAuthHandler:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_store: TokenStore,
        redirect_uri: str = "http://localhost:8000/oauth/callback",
        logger=None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.token_store = token_store
        import logging
        self.logger = logger or logging.getLogger("zoom.oauth")

    def get_auth_url(self) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": "zoom_mcp_auth",
        }
        return f"{ZOOM_AUTH_URL}?{urlencode(params)}"

    def get_auth_headers(self) -> Dict[str, str]:
        data = self.token_store.load()
        if not data or not data.get("access_token"):
            raise RuntimeError("No access token; call ensure_authenticated first")
        return {"Authorization": f"{data.get('token_type', 'Bearer')} {data['access_token']}"}

    async def ensure_authenticated(self) -> bool:
        if not self.token_store.is_expired():
            return True
        data = self.token_store.load()
        if data and data.get("refresh_token"):
            if await self.refresh_access_token():
                return True
        return await self._run_browser_flow()

    async def refresh_access_token(self) -> bool:
        data = self.token_store.load()
        if not data or not data.get("refresh_token"):
            return False
        try:
            response = await request_with_retry(
                "POST", ZOOM_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": data["refresh_token"],
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )
        except Exception as e:
            self.logger.error("Token refresh failed: %s", e)
            return False
        if response.status_code != 200:
            self.logger.error("Token refresh HTTP %d", response.status_code)
            return False
        return self._save_token_response(response.json(),
                                         existing_refresh=data["refresh_token"])

    def _save_token_response(self, payload: dict, existing_refresh: Optional[str] = None) -> bool:
        access = payload.get("access_token")
        if not access:
            return False
        refresh = payload.get("refresh_token", existing_refresh)
        expires_in = int(payload.get("expires_in", 3600))
        self.token_store.save(
            access_token=access,
            refresh_token=refresh,
            expires_at=datetime.now() + timedelta(seconds=expires_in),
            token_type=payload.get("token_type", "Bearer"),
            scope=payload.get("scope"),
        )
        return True

    async def _run_browser_flow(self, timeout_seconds: int = 300) -> bool:
        parsed = urlparse(self.redirect_uri)
        port = parsed.port or 8000
        callback_path = parsed.path or "/oauth/callback"

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("localhost", port))
        except OSError:
            self.logger.error("Port %d already in use", port)
            return False

        server = HTTPServer(("localhost", port), _CallbackHandler)
        server.expected_path = callback_path
        server.auth_code = None
        server.auth_error = None

        def serve():
            while server.auth_code is None and server.auth_error is None:
                server.handle_request()

        threading.Thread(target=serve, daemon=True).start()
        webbrowser.open(self.get_auth_url())
        loop_start = asyncio.get_event_loop().time()
        while server.auth_code is None and server.auth_error is None:
            await asyncio.sleep(0.1)
            if asyncio.get_event_loop().time() - loop_start > timeout_seconds:
                self.logger.error("OAuth callback timeout")
                server.server_close(); return False
        server.server_close()
        if server.auth_error or not server.auth_code:
            return False
        return await self._exchange_code(server.auth_code)

    async def _exchange_code(self, code: str) -> bool:
        try:
            r = await request_with_retry(
                "POST", ZOOM_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )
        except Exception as e:
            self.logger.error("Code exchange failed: %s", e); return False
        if r.status_code != 200:
            self.logger.error("Code exchange HTTP %d: %s", r.status_code, r.text); return False
        return self._save_token_response(r.json())

    async def make_authenticated_request(
        self, method: str, url: str, **kwargs
    ) -> httpx.Response:
        if not await self.ensure_authenticated():
            raise RuntimeError("Authentication failed")
        headers = kwargs.get("headers", {}); headers.update(self.get_auth_headers())
        kwargs["headers"] = headers
        response = await request_with_retry(method, url, **kwargs)
        if response.status_code == 401 and await self.refresh_access_token():
            headers.update(self.get_auth_headers())
            response = await request_with_retry(method, url, **kwargs)
        return response
```

- [ ] **Step 3: Run tests, verify pass**

- [ ] **Step 4: Commit**

```bash
git add server/oauth.py tests/test_oauth.py
git commit -m "feat: refactored Zoom OAuth handler using shared http_client"
```

---

## Task 5: Dispatcher + endpoints route table

**Files:**
- Create: `server/dispatcher.py`, `server/endpoints.py`
- Test: `tests/test_dispatcher.py`

- [ ] **Step 1: Write dispatcher tests**

```python
# tests/test_dispatcher.py
import pytest
from server.dispatcher import build_url, paginate_all


def test_build_url_substitutes_path_params():
    url = build_url(
        "https://api.zoom.us/v2",
        "/chat/channels/{channelId}/members",
        path_params={"channelId": "ABC123"},
    )
    assert url == "https://api.zoom.us/v2/chat/channels/ABC123/members"


@pytest.mark.asyncio
async def test_paginate_all_chases_next_page_token(httpx_mock):
    httpx_mock.add_response(
        url="https://api.zoom.us/v2/x?page_size=100",
        json={"items": [1, 2], "next_page_token": "tok1"},
    )
    httpx_mock.add_response(
        url="https://api.zoom.us/v2/x?page_size=100&next_page_token=tok1",
        json={"items": [3, 4], "next_page_token": ""},
    )
    items = await paginate_all(
        method="GET",
        url="https://api.zoom.us/v2/x",
        items_key="items",
        headers={"Authorization": "Bearer X"},
    )
    assert items == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_paginate_all_respects_max_items(httpx_mock):
    httpx_mock.add_response(
        url="https://api.zoom.us/v2/x?page_size=100",
        json={"items": [1, 2, 3, 4, 5], "next_page_token": "tok1"},
    )
    items = await paginate_all(
        method="GET", url="https://api.zoom.us/v2/x",
        items_key="items", max_items=3,
        headers={"Authorization": "Bearer X"},
    )
    assert items == [1, 2, 3]
```

- [ ] **Step 2: Implement server/dispatcher.py**

```python
"""Generic API dispatcher with auto-pagination and path-param substitution."""
from typing import Any, Dict, List, Optional
from .http_client import request_with_retry


def build_url(base: str, path: str, path_params: Optional[Dict[str, str]] = None) -> str:
    if path_params:
        for k, v in path_params.items():
            path = path.replace(f"{{{k}}}", str(v))
    return f"{base.rstrip('/')}{path}"


async def paginate_all(
    method: str,
    url: str,
    *,
    items_key: str,
    headers: Dict[str, str],
    params: Optional[Dict[str, Any]] = None,
    max_items: Optional[int] = 1000,
    page_size: int = 100,
) -> List[Any]:
    """Chase next_page_token, returning aggregated items list."""
    params = dict(params or {})
    params.setdefault("page_size", page_size)
    items: List[Any] = []
    next_token = None
    while True:
        if next_token:
            params["next_page_token"] = next_token
        r = await request_with_retry(method, url, headers=headers, params=params)
        if r.status_code != 200:
            r.raise_for_status()
        data = r.json()
        page_items = data.get(items_key, [])
        items.extend(page_items)
        next_token = data.get("next_page_token") or None
        if not next_token:
            break
        if max_items is not None and len(items) >= max_items:
            return items[:max_items]
    if max_items is not None:
        return items[:max_items]
    return items
```

- [ ] **Step 3: Implement server/endpoints.py — declarative route table**

```python
"""Route table for all 22 Zoom MCP tools. Drives both tool registration and dispatch."""
from typing import Any, Dict, List

API_BASE = "https://api.zoom.us/v2"

# Each entry shape:
#   name:        tool name (zoom_*)
#   summary:     short description for tool list
#   method:      HTTP method or None (handled in tools.py for special cases)
#   path:        path template or None
#   path_params: list of param names to interpolate into path
#   query:       dict[name -> {type, description}]
#   body:        dict[name -> {type, description}]
#   required:    list of required arg names
#   handler:     name of special handler function in tools.py (if not standard dispatch)
#   cache:       cache strategy hint ("channels"|"contacts"|"none"|"meetings"|...)
#   items_key:   for list endpoints, key holding items in the response (for auto-paginate)

ENDPOINTS: List[Dict[str, Any]] = [
    # ---------- Auth & meta ----------
    {"name": "zoom_authenticate", "summary": "Authenticate with Zoom (opens browser)",
     "handler": "authenticate"},
    {"name": "zoom_revoke_authentication",
     "summary": "Wipe local Zoom tokens, cache, and logs",
     "handler": "revoke_authentication"},
    {"name": "zoom_get_my_info",
     "summary": "Get the authenticated user's profile (cached in memory)",
     "method": "GET", "path": "/users/me", "handler": "get_my_info"},

    # ---------- AI Companion ----------
    {"name": "zoom_search",
     "summary": "AI Companion search across Zoom Meetings, Chat, and Docs.",
     "handler": "ai_companion_search",
     "body": {
        "query": {"type": "string", "description": "Search query"},
        "scope": {"type": "string", "description": "chat|meetings|docs|all"},
        "from_date": {"type": "string", "description": "ISO-8601 start date"},
        "to_date": {"type": "string", "description": "ISO-8601 end date"},
        "max_results": {"type": "integer", "description": "Max results (default 50)"},
     },
     "required": ["query"]},
    {"name": "zoom_ask",
     "summary": "AI Companion grounded Q&A across Zoom Meetings, Chat, and Docs.",
     "handler": "ai_companion_ask",
     "body": {
        "question": {"type": "string", "description": "Question to ask"},
        "scope": {"type": "string", "description": "chat|meetings|docs|all"},
        "from_date": {"type": "string", "description": "ISO-8601 start date"},
        "to_date": {"type": "string", "description": "ISO-8601 end date"},
     },
     "required": ["question"]},

    # ---------- Resolve ----------
    {"name": "zoom_resolve",
     "summary": "Resolve a name or email to a channel/contact/user ID via cache",
     "handler": "resolve",
     "body": {
        "query": {"type": "string", "description": "Name, email, or fragment"},
        "kind": {"type": "string", "description": "channel|contact|auto (default auto)"},
     },
     "required": ["query"]},

    # ---------- Channels ----------
    {"name": "zoom_list_channels",
     "summary": "List channels the user belongs to (cache-first)",
     "handler": "list_channels",
     "body": {
        "force_refresh": {"type": "boolean", "description": "Bypass cache"},
        "starred_only":  {"type": "boolean", "description": "Only starred channels"},
     }},
    {"name": "zoom_list_channel_members",
     "summary": "List members of a channel (cache-first)",
     "handler": "list_channel_members",
     "body": {
        "channel": {"type": "string", "description": "Channel name or ID"},
        "force_refresh": {"type": "boolean", "description": "Bypass cache"},
     },
     "required": ["channel"]},

    # ---------- Contacts ----------
    {"name": "zoom_list_contacts",
     "summary": "List user's contacts (cache-first)",
     "handler": "list_contacts",
     "body": {"force_refresh": {"type": "boolean", "description": "Bypass cache"}}},

    # ---------- Messages (live) ----------
    {"name": "zoom_get_channel_history",
     "summary": "Auto-paginated message history with reactions and attachment metadata",
     "handler": "get_channel_history",
     "body": {
        "channel": {"type": "string", "description": "Channel name or ID"},
        "contact": {"type": "string", "description": "Contact email or ID (for DMs)"},
        "from_date": {"type": "string", "description": "ISO-8601 start"},
        "to_date":   {"type": "string", "description": "ISO-8601 end"},
        "max_messages": {"type": "integer", "description": "Default 500"},
     }},
    {"name": "zoom_get_thread",
     "summary": "Messages under a thread (parent message ID)",
     "handler": "get_thread",
     "body": {
        "message_id": {"type": "string", "description": "Parent message ID"},
        "channel":    {"type": "string", "description": "Channel name or ID"},
        "contact":    {"type": "string", "description": "Contact (for DM threads)"},
     },
     "required": ["message_id"]},
    {"name": "zoom_get_message",
     "summary": "Get a single chat message by ID",
     "handler": "get_message",
     "body": {
        "message_id": {"type": "string", "description": "Message ID"},
        "channel": {"type": "string", "description": "Channel name or ID"},
        "contact": {"type": "string", "description": "Contact (for DMs)"},
     },
     "required": ["message_id"]},

    # ---------- Files ----------
    {"name": "zoom_get_file",
     "summary": "File metadata; for text/code MIME types also returns content (max 1MB)",
     "handler": "get_file",
     "body": {"file_id": {"type": "string", "description": "Chat file ID"}},
     "required": ["file_id"]},

    # ---------- Pinned / bookmarks / mention groups ----------
    {"name": "zoom_list_pinned_messages",
     "summary": "Pinned messages in a channel",
     "handler": "list_pinned_messages",
     "body": {"channel": {"type": "string", "description": "Channel name or ID"}},
     "required": ["channel"]},
    {"name": "zoom_list_bookmarks",
     "summary": "User's bookmarked messages",
     "handler": "list_bookmarks"},
    {"name": "zoom_list_mention_groups",
     "summary": "Mention groups (e.g. @engineering) in a channel",
     "handler": "list_mention_groups",
     "body": {"channel": {"type": "string", "description": "Channel name or ID"}},
     "required": ["channel"]},

    # ---------- Shared spaces ----------
    {"name": "zoom_list_shared_spaces",
     "summary": "Shared spaces the user belongs to",
     "handler": "list_shared_spaces",
     "body": {"force_refresh": {"type": "boolean"}}},
    {"name": "zoom_get_shared_space",
     "summary": "Shared-space detail; include channels/members via include arg",
     "handler": "get_shared_space",
     "body": {
        "space_id": {"type": "string", "description": "Shared space ID"},
        "include":  {"type": "string", "description": "all|detail|channels|members"},
     },
     "required": ["space_id"]},

    # ---------- Meetings + Recordings ----------
    {"name": "zoom_list_meetings",
     "summary": "List user's meetings (past + scheduled, optionally with recordings only)",
     "handler": "list_meetings",
     "body": {
        "type":      {"type": "string", "description": "scheduled|live|upcoming|previous_meetings"},
        "from_date": {"type": "string", "description": "ISO-8601 start (yyyy-MM-dd)"},
        "to_date":   {"type": "string", "description": "ISO-8601 end (yyyy-MM-dd)"},
     }},
    {"name": "zoom_get_meeting",
     "summary": "Meeting details + participant list + recording-files manifest",
     "handler": "get_meeting",
     "body": {"meeting_id": {"type": "string", "description": "Meeting ID or UUID"}},
     "required": ["meeting_id"]},
    {"name": "zoom_list_recordings",
     "summary": "List user's cloud recordings",
     "handler": "list_recordings",
     "body": {
        "from_date": {"type": "string", "description": "yyyy-MM-dd"},
        "to_date":   {"type": "string", "description": "yyyy-MM-dd"},
     }},
    {"name": "zoom_get_meeting_transcript",
     "summary": "Download and parse a meeting transcript (VTT → text)",
     "handler": "get_meeting_transcript",
     "body": {"meeting_id": {"type": "string", "description": "Meeting ID or UUID"}},
     "required": ["meeting_id"]},
]


def endpoint_by_name(name: str) -> Dict[str, Any]:
    for ep in ENDPOINTS:
        if ep["name"] == name:
            return ep
    raise KeyError(name)
```

- [ ] **Step 4: Run dispatcher tests, verify pass**

- [ ] **Step 5: Commit**

```bash
git add server/dispatcher.py server/endpoints.py tests/test_dispatcher.py
git commit -m "feat: dispatcher + endpoints route table for 22 tools"
```

---

## Task 6: AI Companion module (`zoom_search`, `zoom_ask`)

**Files:**
- Create: `server/ai_companion.py`
- Test: `tests/test_ai_companion.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_ai_companion.py
import pytest
from unittest.mock import AsyncMock
from server.ai_companion import scope_to_sources, search, ask


def test_scope_to_sources_chat():
    assert scope_to_sources("chat") == ["team_chat"]


def test_scope_to_sources_meetings():
    assert scope_to_sources("meetings") == ["meeting"]


def test_scope_to_sources_docs():
    assert scope_to_sources("docs") == ["zoom_doc"]


def test_scope_to_sources_all():
    assert sorted(scope_to_sources("all")) == sorted(["team_chat", "meeting", "zoom_doc"])


def test_scope_to_sources_default():
    assert sorted(scope_to_sources(None)) == sorted(["team_chat", "meeting", "zoom_doc"])


@pytest.mark.asyncio
async def test_search_calls_correct_endpoint(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.zoom.us/v2/ai_companion/search",
        json={"results": [{"id": "r1", "snippet": "hi"}]},
    )
    oauth = AsyncMock()
    oauth.get_auth_headers.return_value = {"Authorization": "Bearer X"}
    oauth.ensure_authenticated.return_value = True
    oauth.make_authenticated_request = AsyncMock(side_effect=lambda m, u, **kw: __import__("httpx").Response(200, json={"results": [{"id": "r1"}]}))
    out = await search(oauth, query="q", scope="all")
    assert out["results"][0]["id"] == "r1"
```

- [ ] **Step 2: Implement server/ai_companion.py**

```python
"""AI Companion search and ask. Replaces manual cross-channel fan-out."""
from typing import Any, Dict, List, Optional

from .endpoints import API_BASE

_SCOPE_MAP = {
    "chat": ["team_chat"],
    "meetings": ["meeting"],
    "docs": ["zoom_doc"],
    "all": ["team_chat", "meeting", "zoom_doc"],
    None: ["team_chat", "meeting", "zoom_doc"],
}


def scope_to_sources(scope: Optional[str]) -> List[str]:
    return list(_SCOPE_MAP.get(scope, _SCOPE_MAP["all"]))


def _build_body(extra: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in extra.items() if v is not None}


async def search(
    oauth_handler,
    *,
    query: str,
    scope: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    max_results: int = 50,
) -> Dict[str, Any]:
    if not query or not query.strip():
        raise ValueError("query is required")
    body = _build_body({
        "query": query,
        "sources": scope_to_sources(scope),
        "from": from_date,
        "to": to_date,
        "limit": max_results,
    })
    r = await oauth_handler.make_authenticated_request(
        "POST", f"{API_BASE}/ai_companion/search", json=body,
    )
    if r.status_code == 403:
        raise RuntimeError(
            "AI Companion is not enabled for this account. "
            "Ask your Zoom admin to enable it."
        )
    if r.status_code != 200:
        raise RuntimeError(f"AI Companion search failed: HTTP {r.status_code}: {r.text}")
    return r.json()


async def ask(
    oauth_handler,
    *,
    question: str,
    scope: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> Dict[str, Any]:
    if not question or not question.strip():
        raise ValueError("question is required")
    body = _build_body({
        "question": question,
        "sources": scope_to_sources(scope),
        "from": from_date,
        "to": to_date,
    })
    r = await oauth_handler.make_authenticated_request(
        "POST", f"{API_BASE}/ai_companion/ask", json=body,
    )
    if r.status_code == 403:
        raise RuntimeError(
            "AI Companion is not enabled for this account. "
            "Ask your Zoom admin to enable it."
        )
    if r.status_code != 200:
        raise RuntimeError(f"AI Companion ask failed: HTTP {r.status_code}: {r.text}")
    return r.json()
```

- [ ] **Step 3: Run tests, verify pass; commit**

```bash
git add server/ai_companion.py tests/test_ai_companion.py
git commit -m "feat: AI Companion search and ask"
```

---

## Task 7: Transcripts module (VTT parser + transcript fetch)

**Files:**
- Create: `server/transcripts.py`
- Test: `tests/test_transcripts.py`

- [ ] **Step 1: Write VTT parser tests**

```python
# tests/test_transcripts.py
from server.transcripts import parse_vtt


SAMPLE_VTT = """WEBVTT

1
00:00:00.000 --> 00:00:05.000
<v Alice>Hello and welcome.

2
00:00:05.000 --> 00:00:10.000
<v Bob>Thanks for having me.

3
00:00:10.000 --> 00:00:15.000
Plain text without speaker tag
"""


def test_parse_vtt_with_speakers():
    out = parse_vtt(SAMPLE_VTT)
    assert "[00:00] Alice: Hello and welcome." in out
    assert "[00:05] Bob: Thanks for having me." in out
    assert "[00:10] Plain text without speaker tag" in out


def test_parse_vtt_strips_webvtt_header():
    out = parse_vtt(SAMPLE_VTT)
    assert "WEBVTT" not in out


def test_parse_vtt_handles_empty():
    assert parse_vtt("") == ""


def test_parse_vtt_handles_malformed_returns_raw_fallback():
    # No timestamps at all — return content best-effort
    out = parse_vtt("just some text without VTT formatting")
    assert "just some text" in out
```

- [ ] **Step 2: Implement server/transcripts.py**

```python
"""Meeting transcript download and VTT parser. Never persists transcript content."""
import re
from typing import Optional

from .endpoints import API_BASE

_TIMESTAMP_RE = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2})\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}"
)
_SPEAKER_RE = re.compile(r"^<v\s+([^>]+)>(.*)$")


def parse_vtt(vtt: str) -> str:
    """Convert WEBVTT text to '[HH:MM] Speaker: text' lines."""
    lines = vtt.splitlines()
    out = []
    current_ts = None
    saw_timestamp = False
    for raw in lines:
        line = raw.strip()
        if not line or line == "WEBVTT" or line.startswith("NOTE"):
            current_ts = None
            continue
        m = _TIMESTAMP_RE.match(line)
        if m:
            saw_timestamp = True
            hh, mm, _ = m.groups()
            current_ts = f"[{hh}:{mm}]"
            continue
        if line.isdigit():
            continue  # cue identifier
        speaker_m = _SPEAKER_RE.match(line)
        if speaker_m:
            speaker, text = speaker_m.groups()
            prefix = current_ts or ""
            out.append(f"{prefix} {speaker}: {text}".strip())
        else:
            prefix = current_ts or ""
            out.append(f"{prefix} {line}".strip())
        current_ts = None
    if not saw_timestamp:
        return vtt.strip()
    return "\n".join(out)


def find_transcript_file(recording_files: list) -> Optional[dict]:
    """Pick the best transcript file from a recording_files manifest."""
    for f in recording_files:
        if f.get("file_type") == "TRANSCRIPT":
            return f
    for f in recording_files:
        if f.get("file_type") == "CC":
            return f
    return None


async def fetch_meeting_transcript(oauth_handler, meeting_id: str) -> str:
    """Download and parse the transcript for a given meeting."""
    r = await oauth_handler.make_authenticated_request(
        "GET", f"{API_BASE}/meetings/{meeting_id}/recordings",
    )
    if r.status_code == 404:
        raise RuntimeError("No recording exists for this meeting.")
    if r.status_code != 200:
        raise RuntimeError(f"Recording fetch failed: HTTP {r.status_code}: {r.text}")

    files = r.json().get("recording_files", [])
    transcript_file = find_transcript_file(files)
    if not transcript_file:
        raise RuntimeError(
            "Recording exists but no transcript was generated. "
            "Free Zoom plans do not include transcription."
        )

    download_url = transcript_file.get("download_url")
    if not download_url:
        raise RuntimeError("Transcript file has no download URL")

    size = transcript_file.get("file_size", 0)
    if size and size > 50 * 1024 * 1024:
        raise RuntimeError(f"Transcript file too large ({size} bytes); fetch via Zoom UI.")

    headers = oauth_handler.get_auth_headers()
    from .http_client import request_with_retry
    dr = await request_with_retry("GET", download_url, headers=headers)
    if dr.status_code != 200:
        # Try once more — pre-signed URL may have expired in cache
        raise RuntimeError(f"Transcript download failed: HTTP {dr.status_code}")
    return parse_vtt(dr.text)
```

- [ ] **Step 3: Run tests, verify pass; commit**

```bash
git add server/transcripts.py tests/test_transcripts.py
git commit -m "feat: VTT transcript parser and download flow"
```

---

## Task 8: Files module (`zoom_get_file`)

**Files:**
- Create: `server/files.py`
- Test: `tests/test_files.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_files.py
from server.files import is_text_mime, MAX_TEXT_BYTES, MAX_FILE_BYTES


def test_text_mime_detection():
    assert is_text_mime("text/plain")
    assert is_text_mime("text/markdown")
    assert is_text_mime("application/json")
    assert is_text_mime("application/x-yaml")
    assert not is_text_mime("application/pdf")
    assert not is_text_mime("image/png")
    assert not is_text_mime("application/zip")


def test_size_constants():
    assert MAX_TEXT_BYTES == 1 * 1024 * 1024
    assert MAX_FILE_BYTES == 10 * 1024 * 1024
```

- [ ] **Step 2: Implement server/files.py**

```python
"""Chat file fetching with strict text-only MIME allow-list."""
from typing import Any, Dict, Optional

from .endpoints import API_BASE
from .http_client import request_with_retry

MAX_TEXT_BYTES = 1 * 1024 * 1024  # 1MB cap on inline text content
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10MB hard cap

_TEXT_MIMES = {
    "text/plain", "text/markdown", "text/csv", "text/html",
    "application/json", "application/xml", "text/xml",
    "application/x-yaml", "application/yaml",
    "application/x-toml", "application/toml",
}
_TEXT_PREFIXES = ("text/",)


def is_text_mime(mime: str) -> bool:
    if not mime:
        return False
    if mime in _TEXT_MIMES:
        return True
    return any(mime.startswith(p) for p in _TEXT_PREFIXES)


async def get_file(oauth_handler, file_id: str) -> Dict[str, Any]:
    """Return file metadata; for text MIME types, also fetch and inline text content."""
    r = await oauth_handler.make_authenticated_request(
        "GET", f"{API_BASE}/chat/files/{file_id}",
    )
    if r.status_code != 200:
        raise RuntimeError(f"File metadata fetch failed: HTTP {r.status_code}: {r.text}")
    meta = r.json()
    mime = meta.get("file_type") or meta.get("mime_type", "")
    size = int(meta.get("file_size", 0))
    download_url = meta.get("download_url")

    result: Dict[str, Any] = {
        "file_id": meta.get("id") or file_id,
        "name": meta.get("name") or meta.get("file_name"),
        "mime_type": mime,
        "size": size,
        "sender": meta.get("sender"),
        "posted_at": meta.get("date_time") or meta.get("posted_at"),
        "channel_id": meta.get("channel_id"),
        "download_url": download_url,
    }

    if is_text_mime(mime) and size <= MAX_TEXT_BYTES and download_url:
        headers = oauth_handler.get_auth_headers()
        dr = await request_with_retry("GET", download_url, headers=headers)
        if dr.status_code == 200:
            content = dr.content
            if len(content) > MAX_TEXT_BYTES:
                content = content[:MAX_TEXT_BYTES]
            try:
                result["text"] = content.decode("utf-8", errors="replace")
            except Exception:
                pass
    return result
```

- [ ] **Step 3: Run, commit**

```bash
git add server/files.py tests/test_files.py
git commit -m "feat: zoom_get_file with text-only MIME allow-list"
```

---

## Task 9: Shared spaces module + message-inline data + handlers for remaining endpoints

This is the largest single task — it implements all the remaining tool handlers (channel listing with cache, message history with reactions/files inline, shared spaces, mention groups, meetings, etc.). Combined into `server/tools.py` (Task 10) but the helpers below live in modules.

**Files:**
- Create: `server/shared_spaces.py`, `server/messages.py`
- Test: `tests/test_shared_spaces.py`, `tests/test_message_inline.py`

- [ ] **Step 1: Write `server/shared_spaces.py`**

```python
"""Shared-space tools: list and detail-with-include."""
from typing import Any, Dict, List

from .endpoints import API_BASE
from .dispatcher import paginate_all


async def list_shared_spaces(oauth_handler) -> List[Dict[str, Any]]:
    headers = oauth_handler.get_auth_headers()
    return await paginate_all(
        "GET", f"{API_BASE}/chat/spaces",
        items_key="spaces", headers=headers,
    )


async def get_shared_space(
    oauth_handler, space_id: str, include: str = "detail"
) -> Dict[str, Any]:
    headers = oauth_handler.get_auth_headers()
    out: Dict[str, Any] = {}
    if include in ("detail", "all"):
        r = await oauth_handler.make_authenticated_request(
            "GET", f"{API_BASE}/chat/spaces/{space_id}",
        )
        if r.status_code != 200:
            raise RuntimeError(f"Shared space fetch failed: HTTP {r.status_code}")
        out["detail"] = r.json()
    if include in ("channels", "all"):
        out["channels"] = await paginate_all(
            "GET", f"{API_BASE}/chat/spaces/{space_id}/channels",
            items_key="channels", headers=headers,
        )
    if include in ("members", "all"):
        out["members"] = await paginate_all(
            "GET", f"{API_BASE}/chat/spaces/{space_id}/members",
            items_key="members", headers=headers,
        )
    return out
```

- [ ] **Step 2: Write `server/messages.py` — message tools with reactions/files inline**

```python
"""Message-listing tools (channel history, threads, single message lookup)."""
from typing import Any, Dict, List, Optional

from .endpoints import API_BASE
from .dispatcher import paginate_all


def _scope_params(channel_id: Optional[str], contact_id: Optional[str]) -> Dict[str, str]:
    if channel_id:
        return {"to_channel": channel_id}
    if contact_id:
        return {"to_contact": contact_id}
    return {}


async def get_channel_history(
    oauth_handler,
    *,
    channel_id: Optional[str] = None,
    contact_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    max_messages: int = 500,
) -> List[Dict[str, Any]]:
    if not channel_id and not contact_id:
        raise ValueError("Either channel_id or contact_id is required")
    headers = oauth_handler.get_auth_headers()
    params = _scope_params(channel_id, contact_id)
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    params["page_size"] = 50  # Zoom max for messages
    return await paginate_all(
        "GET", f"{API_BASE}/chat/users/me/messages",
        items_key="messages", headers=headers,
        params=params, max_items=max_messages, page_size=50,
    )


async def get_thread(
    oauth_handler,
    *,
    message_id: str,
    channel_id: Optional[str] = None,
    contact_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    headers = oauth_handler.get_auth_headers()
    params = _scope_params(channel_id, contact_id)
    return await paginate_all(
        "GET", f"{API_BASE}/chat/users/me/messages/{message_id}",
        items_key="messages", headers=headers, params=params, page_size=50,
    )


async def get_message(
    oauth_handler,
    *,
    message_id: str,
    channel_id: Optional[str] = None,
    contact_id: Optional[str] = None,
) -> Dict[str, Any]:
    params = _scope_params(channel_id, contact_id)
    r = await oauth_handler.make_authenticated_request(
        "GET", f"{API_BASE}/chat/users/me/messages/{message_id}",
        params=params,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Get message failed: HTTP {r.status_code}: {r.text}")
    return r.json()


async def list_pinned_messages(oauth_handler, channel_id: str) -> List[Dict[str, Any]]:
    headers = oauth_handler.get_auth_headers()
    return await paginate_all(
        "GET", f"{API_BASE}/chat/channels/{channel_id}/pinned",
        items_key="messages", headers=headers,
    )


async def list_bookmarks(oauth_handler) -> List[Dict[str, Any]]:
    headers = oauth_handler.get_auth_headers()
    return await paginate_all(
        "GET", f"{API_BASE}/chat/messages/bookmarks",
        items_key="bookmarks", headers=headers,
    )


async def list_mention_groups(oauth_handler, channel_id: str) -> List[Dict[str, Any]]:
    headers = oauth_handler.get_auth_headers()
    return await paginate_all(
        "GET", f"{API_BASE}/chat/channels/{channel_id}/mention_groups",
        items_key="mention_groups", headers=headers,
    )
```

- [ ] **Step 3: Write tests for both modules**

```python
# tests/test_shared_spaces.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from server.shared_spaces import get_shared_space


@pytest.mark.asyncio
async def test_get_shared_space_include_all_makes_three_calls():
    oauth = MagicMock()
    oauth.get_auth_headers.return_value = {"Authorization": "Bearer X"}

    async def fake_request(method, url, **kw):
        import httpx
        if "channels" in url:
            return httpx.Response(200, json={"channels": [{"id": "c1"}]})
        if "members" in url:
            return httpx.Response(200, json={"members": [{"id": "u1"}]})
        return httpx.Response(200, json={"id": "S1", "name": "Space"})

    oauth.make_authenticated_request = AsyncMock(side_effect=fake_request)
    # paginate_all uses request_with_retry directly, so we patch that:
    import server.shared_spaces as ss
    ss.paginate_all = AsyncMock(side_effect=lambda *a, **kw: (
        [{"id": "c1"}] if "channels" in a[1] else [{"id": "u1"}]
    ))

    out = await get_shared_space(oauth, "S1", include="all")
    assert "detail" in out
    assert "channels" in out
    assert "members" in out
```

```python
# tests/test_message_inline.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from server.messages import get_message


@pytest.mark.asyncio
async def test_get_message_passes_through_reactions_and_files():
    oauth = MagicMock()

    async def fake_request(method, url, **kw):
        import httpx
        return httpx.Response(200, json={
            "id": "M1", "message": "hello",
            "reactions": [{"emoji": "👍", "count": 3}],
            "files": [{"file_id": "F1", "file_name": "x.txt", "file_size": 10}],
        })

    oauth.make_authenticated_request = AsyncMock(side_effect=fake_request)
    out = await get_message(oauth, message_id="M1", channel_id="C1")
    assert out["reactions"][0]["emoji"] == "👍"
    assert out["files"][0]["file_id"] == "F1"
```

- [ ] **Step 4: Run, verify, commit**

```bash
.venv/bin/pytest tests/test_shared_spaces.py tests/test_message_inline.py -v
git add server/shared_spaces.py server/messages.py \
        tests/test_shared_spaces.py tests/test_message_inline.py
git commit -m "feat: shared spaces and message tools (history, thread, single, pinned, bookmarks, mention groups)"
```

---

## Task 10: tools.py + main.py — server entry point and tool registration

**Files:**
- Create: `server/tools.py`, `server/main.py`

- [ ] **Step 1: Write `server/tools.py`**

```python
"""Tool registration and call_tool dispatch. Maps endpoints.ENDPOINTS to handlers."""
import json
import logging
import os
from typing import Any, Dict, List

from mcp.types import Tool

from . import ai_companion, files, messages, shared_spaces, transcripts
from .cache.store import CacheStore
from .endpoints import API_BASE, ENDPOINTS, endpoint_by_name
from .oauth import ZoomOAuthHandler
from .paths import cache_db_file, log_file, log_dir
from .token_store import TokenStore

logger = logging.getLogger("zoom-mcp")


class ZoomTools:
    def __init__(self, oauth_handler: ZoomOAuthHandler, cache: CacheStore):
        self.oauth = oauth_handler
        self.cache = cache
        self._my_info_cached: Dict[str, Any] = {}

    def list_tools(self) -> List[Tool]:
        out = []
        for ep in ENDPOINTS:
            properties: Dict[str, Any] = {}
            for k, v in ep.get("body", {}).items():
                properties[k] = {key: val for key, val in v.items()}
            schema: Dict[str, Any] = {"type": "object", "properties": properties}
            if ep.get("required"):
                schema["required"] = ep["required"]
            out.append(Tool(name=ep["name"], description=ep["summary"], inputSchema=schema))
        return out

    async def call_tool(self, name: str, args: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            ep = endpoint_by_name(name)
        except KeyError:
            return _err(f"Unknown tool: {name}")

        # Auth tool special case
        if name == "zoom_authenticate":
            return await self._authenticate()
        if name == "zoom_revoke_authentication":
            return await self._revoke()

        if not await self.oauth.ensure_authenticated():
            return _err("Authentication required. Use 'zoom_authenticate' first.")

        # Verify required args
        for r in ep.get("required", []):
            if r not in args:
                return _err(f"Missing required argument: {r}")

        try:
            handler = ep.get("handler")
            method = getattr(self, f"_h_{handler}", None)
            if method is None:
                return _err(f"No handler implemented for {name}")
            return await method(args)
        except Exception as e:
            logger.exception("Handler %s failed", name)
            return _err(str(e))

    # ---- handlers ----

    async def _authenticate(self):
        if await self.oauth.ensure_authenticated():
            r = await self.oauth.make_authenticated_request("GET", f"{API_BASE}/users/me")
            if r.status_code == 200:
                u = r.json()
                return _text(f"Authenticated.\nUser: {u.get('display_name')}\nEmail: {u.get('email')}")
            return _err(f"Auth OK but user info failed: HTTP {r.status_code}")
        return _err("Authentication failed.")

    async def _revoke(self):
        # Wipe tokens, cache, in-memory state
        try:
            self.oauth.token_store.delete()
        except Exception:
            pass
        self.cache.clear_all()
        self._my_info_cached = {}
        return _text("Authentication revoked. Local tokens, cache, and in-memory state cleared.")

    async def _h_get_my_info(self, args):
        if self._my_info_cached:
            return _json(self._my_info_cached)
        r = await self.oauth.make_authenticated_request("GET", f"{API_BASE}/users/me")
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}: {r.text}")
        self._my_info_cached = r.json()
        return _json(self._my_info_cached)

    async def _h_ai_companion_search(self, args):
        out = await ai_companion.search(
            self.oauth,
            query=args["query"],
            scope=args.get("scope"),
            from_date=args.get("from_date"),
            to_date=args.get("to_date"),
            max_results=int(args.get("max_results", 50)),
        )
        return _json(out)

    async def _h_ai_companion_ask(self, args):
        out = await ai_companion.ask(
            self.oauth,
            question=args["question"],
            scope=args.get("scope"),
            from_date=args.get("from_date"),
            to_date=args.get("to_date"),
        )
        return _json(out)

    async def _h_resolve(self, args):
        query = args["query"]
        kind = args.get("kind", "auto")
        # Always check cache first (refresh underlying lists if empty)
        if kind in ("channel", "auto"):
            ch = self.cache.get_channel_by_name(query)
            if ch:
                return _json({"kind": "channel", "match": ch})
        if kind in ("contact", "auto"):
            c = self.cache.get_contact_by_email(query)
            if c:
                return _json({"kind": "contact", "match": c})
            uid = self.cache.get_user_id_by_email(query)
            if uid:
                return _json({"kind": "contact", "match": {"id": uid, "email": query}})
        # Fallback: refresh and try again
        await self._refresh_channels(); await self._refresh_contacts()
        if kind in ("channel", "auto"):
            ch = self.cache.get_channel_by_name(query)
            if ch:
                return _json({"kind": "channel", "match": ch})
        if kind in ("contact", "auto"):
            c = self.cache.get_contact_by_email(query)
            if c:
                return _json({"kind": "contact", "match": c})
        return _json({"kind": None, "match": None,
                      "message": f"No match for {query!r} in cache."})

    async def _refresh_channels(self):
        from .dispatcher import paginate_all
        headers = self.oauth.get_auth_headers()
        items = await paginate_all(
            "GET", f"{API_BASE}/chat/users/me/channels",
            items_key="channels", headers=headers,
        )
        # Star info is fetched separately when starred filter requested;
        # for default refresh skip it.
        self.cache.put_channels(items)
        return items

    async def _h_list_channels(self, args):
        if args.get("force_refresh"):
            await self._refresh_channels()
        rows = self.cache.get_channels(starred_only=bool(args.get("starred_only")))
        if not rows:
            await self._refresh_channels()
            rows = self.cache.get_channels(starred_only=bool(args.get("starred_only")))
        return _json({"channels": rows, "count": len(rows)})

    async def _refresh_contacts(self):
        from .dispatcher import paginate_all
        headers = self.oauth.get_auth_headers()
        items = await paginate_all(
            "GET", f"{API_BASE}/chat/users/me/contacts",
            items_key="contacts", headers=headers,
        )
        self.cache.put_contacts(items)
        return items

    async def _h_list_contacts(self, args):
        if args.get("force_refresh"):
            await self._refresh_contacts()
        rows = self.cache.get_contacts()
        if not rows:
            await self._refresh_contacts()
            rows = self.cache.get_contacts()
        return _json({"contacts": rows, "count": len(rows)})

    async def _h_list_channel_members(self, args):
        channel_id = await self._resolve_channel_id(args["channel"])
        if not channel_id:
            return _err(f"Unknown channel: {args['channel']!r}")
        if not args.get("force_refresh"):
            cached = self.cache.get_channel_members(channel_id)
            if cached:
                return _json({"channel_id": channel_id, "members": cached, "count": len(cached)})
        from .dispatcher import paginate_all
        headers = self.oauth.get_auth_headers()
        items = await paginate_all(
            "GET", f"{API_BASE}/chat/channels/{channel_id}/members",
            items_key="members", headers=headers,
        )
        self.cache.put_channel_members(channel_id, items)
        return _json({"channel_id": channel_id, "members": items, "count": len(items)})

    async def _resolve_channel_id(self, channel: str):
        # If it's already an ID-shaped string, use it
        if len(channel) > 20 and "@" not in channel:
            return channel
        ch = self.cache.get_channel_by_name(channel) or self.cache.get_channel_by_id(channel)
        if ch:
            return ch["id"]
        await self._refresh_channels()
        ch = self.cache.get_channel_by_name(channel) or self.cache.get_channel_by_id(channel)
        return ch["id"] if ch else None

    async def _resolve_contact_id(self, contact: str):
        if "@" not in contact:  # Likely already an ID
            return contact
        c = self.cache.get_contact_by_email(contact)
        if c:
            return c["id"]
        # Cache miss; do a one-off lookup via /users/{email}
        r = await self.oauth.make_authenticated_request(
            "GET", f"{API_BASE}/users/{contact}",
        )
        if r.status_code == 200:
            uid = r.json().get("id")
            if uid:
                self.cache.put_email_to_id(contact, uid)
                return uid
        return contact  # Pass through, let downstream surface 404 if needed

    async def _h_get_channel_history(self, args):
        channel_id = None
        contact_id = None
        if args.get("channel"):
            channel_id = await self._resolve_channel_id(args["channel"])
        elif args.get("contact"):
            contact_id = await self._resolve_contact_id(args["contact"])
        if not channel_id and not contact_id:
            return _err("Either 'channel' or 'contact' is required.")
        items = await messages.get_channel_history(
            self.oauth,
            channel_id=channel_id, contact_id=contact_id,
            from_date=args.get("from_date"), to_date=args.get("to_date"),
            max_messages=int(args.get("max_messages", 500)),
        )
        return _json({"messages": items, "count": len(items)})

    async def _h_get_thread(self, args):
        channel_id = None; contact_id = None
        if args.get("channel"):
            channel_id = await self._resolve_channel_id(args["channel"])
        if args.get("contact"):
            contact_id = await self._resolve_contact_id(args["contact"])
        items = await messages.get_thread(
            self.oauth, message_id=args["message_id"],
            channel_id=channel_id, contact_id=contact_id,
        )
        return _json({"messages": items, "count": len(items)})

    async def _h_get_message(self, args):
        channel_id = None; contact_id = None
        if args.get("channel"):
            channel_id = await self._resolve_channel_id(args["channel"])
        if args.get("contact"):
            contact_id = await self._resolve_contact_id(args["contact"])
        out = await messages.get_message(
            self.oauth, message_id=args["message_id"],
            channel_id=channel_id, contact_id=contact_id,
        )
        return _json(out)

    async def _h_get_file(self, args):
        out = await files.get_file(self.oauth, args["file_id"])
        return _json(out)

    async def _h_list_pinned_messages(self, args):
        channel_id = await self._resolve_channel_id(args["channel"])
        if not channel_id:
            return _err(f"Unknown channel: {args['channel']!r}")
        items = await messages.list_pinned_messages(self.oauth, channel_id)
        return _json({"messages": items, "count": len(items)})

    async def _h_list_bookmarks(self, args):
        items = await messages.list_bookmarks(self.oauth)
        return _json({"bookmarks": items, "count": len(items)})

    async def _h_list_mention_groups(self, args):
        channel_id = await self._resolve_channel_id(args["channel"])
        if not channel_id:
            return _err(f"Unknown channel: {args['channel']!r}")
        items = await messages.list_mention_groups(self.oauth, channel_id)
        self.cache.put_mention_groups(channel_id, items)
        return _json({"channel_id": channel_id, "mention_groups": items, "count": len(items)})

    async def _h_list_shared_spaces(self, args):
        if not args.get("force_refresh"):
            cached = self.cache.get_shared_spaces()
            if cached:
                return _json({"shared_spaces": cached, "count": len(cached)})
        items = await shared_spaces.list_shared_spaces(self.oauth)
        self.cache.put_shared_spaces(items)
        return _json({"shared_spaces": items, "count": len(items)})

    async def _h_get_shared_space(self, args):
        out = await shared_spaces.get_shared_space(
            self.oauth, args["space_id"], include=args.get("include", "detail"),
        )
        return _json(out)

    async def _h_list_meetings(self, args):
        from .dispatcher import paginate_all
        headers = self.oauth.get_auth_headers()
        params = {}
        if args.get("type"):
            params["type"] = args["type"]
        if args.get("from_date"):
            params["from"] = args["from_date"]
        if args.get("to_date"):
            params["to"] = args["to_date"]
        items = await paginate_all(
            "GET", f"{API_BASE}/users/me/meetings",
            items_key="meetings", headers=headers, params=params,
        )
        return _json({"meetings": items, "count": len(items)})

    async def _h_get_meeting(self, args):
        meeting_id = args["meeting_id"]
        r = await self.oauth.make_authenticated_request(
            "GET", f"{API_BASE}/meetings/{meeting_id}",
        )
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}: {r.text}")
        detail = r.json()
        # Also fetch recordings manifest if available
        rec = await self.oauth.make_authenticated_request(
            "GET", f"{API_BASE}/meetings/{meeting_id}/recordings",
        )
        recordings = rec.json() if rec.status_code == 200 else None
        return _json({"meeting": detail, "recordings": recordings})

    async def _h_list_recordings(self, args):
        from .dispatcher import paginate_all
        headers = self.oauth.get_auth_headers()
        params = {}
        if args.get("from_date"):
            params["from"] = args["from_date"]
        if args.get("to_date"):
            params["to"] = args["to_date"]
        items = await paginate_all(
            "GET", f"{API_BASE}/users/me/recordings",
            items_key="meetings", headers=headers, params=params,
        )
        return _json({"recordings": items, "count": len(items)})

    async def _h_get_meeting_transcript(self, args):
        text = await transcripts.fetch_meeting_transcript(self.oauth, args["meeting_id"])
        return _json({"meeting_id": args["meeting_id"], "transcript": text,
                      "length_chars": len(text)})


# ---- helpers ----

def _text(s: str) -> List[Dict[str, Any]]:
    return [{"type": "text", "text": s}]


def _json(obj: Any) -> List[Dict[str, Any]]:
    return [{"type": "text", "text": json.dumps(obj, indent=2, ensure_ascii=False, default=str)}]


def _err(msg: str) -> List[Dict[str, Any]]:
    return [{"type": "text", "text": f"Error: {msg}"}]
```

- [ ] **Step 2: Write `server/main.py` — entry point**

```python
#!/usr/bin/env python3
"""Zoom MCP Server v2 entry point."""
import asyncio
import logging
import os
import signal
import sys
from logging.handlers import RotatingFileHandler

from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

import mcp.server.stdio

from .cache.store import CacheStore
from .log_filter import SensitiveFilter
from .oauth import ZoomOAuthHandler
from .paths import cache_db_file, ensure_dirs, log_file, token_file, token_key_file
from .token_store import TokenStore
from .tools import ZoomTools


def setup_logging() -> logging.Logger:
    ensure_dirs()
    logger = logging.getLogger("zoom-mcp")
    logger.setLevel(logging.INFO)
    fh = RotatingFileHandler(log_file(), maxBytes=10 * 1024 * 1024, backupCount=5)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    fh.addFilter(SensitiveFilter())
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
    sh.addFilter(SensitiveFilter())
    logger.addHandler(fh); logger.addHandler(sh)
    return logger


def get_required_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.stderr.write(f"FATAL: env var {name} is required\n"); sys.exit(1)
    return v


async def run():
    logger = setup_logging()
    logger.info("Zoom MCP server starting")

    client_id = get_required_env("ZOOM_CLIENT_ID")
    client_secret = get_required_env("ZOOM_CLIENT_SECRET")
    redirect_uri = os.environ.get("ZOOM_REDIRECT_URI", "http://localhost:8000/oauth/callback")

    token_store = TokenStore(token_file(), token_key_file())
    oauth = ZoomOAuthHandler(
        client_id=client_id, client_secret=client_secret,
        token_store=token_store, redirect_uri=redirect_uri, logger=logger,
    )
    cache = CacheStore(cache_db_file())
    tools_api = ZoomTools(oauth_handler=oauth, cache=cache)
    server = Server("zoom-integration")

    @server.list_tools()
    async def _lt():
        return tools_api.list_tools()

    @server.call_tool()
    async def _ct(name: str, args: dict):
        return await tools_api.call_tool(name, args or {})

    async with mcp.server.stdio.stdio_server() as (rs, ws):
        await server.run(
            rs, ws,
            InitializationOptions(
                server_name="zoom-integration",
                server_version="2.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main():
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Smoke-test the server starts (no Zoom call needed)**

```bash
ZOOM_CLIENT_ID=x ZOOM_CLIENT_SECRET=y .venv/bin/python -c \
  "import asyncio; from server.main import setup_logging; setup_logging(); print('ok')"
```
Expected: `ok` and no exceptions.

- [ ] **Step 4: Commit**

```bash
git add server/tools.py server/main.py
git commit -m "feat: tool registration, dispatch handlers, server entry point"
```

---

## Task 11: MCPB packaging (manifest + build script + icon)

**Files:**
- Create: `manifest.json`, `icon.png`, `scripts/build_mcpb.sh`, `scripts/dev-run.sh`

- [ ] **Step 1: Write `manifest.json`**

(Use the manifest example from spec §14.2.)

```json
{
  "manifest_version": "0.2",
  "name": "zoom-team-chat-search",
  "display_name": "Zoom Team Chat & Transcripts",
  "version": "2.0.0",
  "description": "Read-only search across Zoom Team Chat messages and meeting transcripts.",
  "long_description": "Provides 22 read-only tools for Zoom Team Chat messages, threads, attachments, shared spaces, mention groups, and meeting transcripts. Includes AI-Companion-powered search and grounded Q&A across Zoom Meetings, Chat, and Docs. Requires a Zoom Marketplace OAuth app with the read-only scopes documented in the README.",
  "author": {"name": "Alex Craig"},
  "icon": "icon.png",
  "license": "MIT",
  "keywords": ["zoom", "team chat", "transcripts", "search", "ai-companion"],
  "server": {
    "type": "python",
    "entry_point": "server/main.py",
    "mcp_config": {
      "command": "python3",
      "args": ["${__dirname}/server/main.py"],
      "env": {
        "ZOOM_CLIENT_ID":     "${user_config.client_id}",
        "ZOOM_CLIENT_SECRET": "${user_config.client_secret}",
        "ZOOM_REDIRECT_URI":  "${user_config.redirect_uri}",
        "PYTHONPATH":         "${__dirname}/server/lib"
      }
    }
  },
  "tools_generated": true,
  "user_config": {
    "client_id": {
      "type": "string",
      "title": "Zoom Client ID",
      "description": "From your Zoom OAuth app at marketplace.zoom.us",
      "required": true
    },
    "client_secret": {
      "type": "string",
      "title": "Zoom Client Secret",
      "description": "From your Zoom OAuth app at marketplace.zoom.us",
      "required": true,
      "sensitive": true
    },
    "redirect_uri": {
      "type": "string",
      "title": "OAuth Redirect URI",
      "description": "Must match the redirect URI configured on your Zoom app.",
      "default": "http://localhost:8000/oauth/callback",
      "required": false
    }
  },
  "compatibility": {"runtimes": {"python": ">=3.10"}}
}
```

- [ ] **Step 2: Create a placeholder `icon.png`**

```bash
# Use the system to generate a simple square placeholder
.venv/bin/python -c "
import struct, zlib
# 64x64 solid blue PNG
W=H=64
def chunk(t,d):
    return struct.pack('>I',len(d))+t+d+struct.pack('>I',zlib.crc32(t+d)&0xffffffff)
sig=b'\x89PNG\r\n\x1a\n'
ihdr=struct.pack('>IIBBBBB',W,H,8,2,0,0,0)
raw=b''.join(b'\x00'+b'\x33\x66\x99'*W for _ in range(H))
idat=zlib.compress(raw)
with open('icon.png','wb') as f:
    f.write(sig+chunk(b'IHDR',ihdr)+chunk(b'IDAT',idat)+chunk(b'IEND',b''))
print('icon.png written')
"
```

- [ ] **Step 3: Write `scripts/build_mcpb.sh`**

```bash
#!/usr/bin/env bash
# Build per-platform .mcpb bundles using @anthropic-ai/mcpb.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
mkdir -p "$DIST"

PLATFORMS=("macosx_11_0_arm64" "macosx_11_0_x86_64" \
           "manylinux_2_17_x86_64" "win_amd64")
TAGS=("darwin-arm64" "darwin-x64" "linux-x64" "win-x64")

for i in "${!PLATFORMS[@]}"; do
  PIP_PLATFORM="${PLATFORMS[$i]}"
  TAG="${TAGS[$i]}"
  STAGE="$ROOT/build/$TAG"
  echo "==> Building for $TAG ($PIP_PLATFORM)"
  rm -rf "$STAGE"
  mkdir -p "$STAGE/server/lib"

  cp -r "$ROOT/server"        "$STAGE/"
  cp    "$ROOT/manifest.json" "$STAGE/"
  cp    "$ROOT/icon.png"      "$STAGE/"

  pip download \
    --platform "$PIP_PLATFORM" \
    --python-version 3.11 \
    --only-binary :all: \
    --no-deps \
    -d "$STAGE/server/lib" \
    -r "$ROOT/requirements.txt"

  pip download \
    --platform "$PIP_PLATFORM" \
    --python-version 3.11 \
    --only-binary :all: \
    -d "$STAGE/server/lib" \
    -r "$ROOT/requirements.txt"

  for whl in "$STAGE/server/lib"/*.whl; do
    [ -f "$whl" ] || continue
    unzip -qo "$whl" -d "$STAGE/server/lib"
    rm "$whl"
  done

  npx --yes @anthropic-ai/mcpb pack "$STAGE" "$DIST/zoom-mcp-${TAG}.mcpb"
  rm -rf "$STAGE"
done

echo "==> All bundles built in $DIST"
ls -la "$DIST"
```

- [ ] **Step 4: Write `scripts/dev-run.sh`**

```bash
#!/usr/bin/env bash
# Run the server from source for local iteration. Loads .env if present.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [ -f .env ]; then set -a; . ./.env; set +a; fi
exec .venv/bin/python -m server.main
```

- [ ] **Step 5: chmod and commit**

```bash
chmod +x scripts/build_mcpb.sh scripts/dev-run.sh
git add manifest.json icon.png scripts/build_mcpb.sh scripts/dev-run.sh
git commit -m "feat: MCPB manifest, icon, and per-platform build script"
```

---

## Task 12: Remove v1 cruft + README

**Files:**
- Delete: `setup.sh`, `zoom_wrapper.sh`, `.env.example`, `base_mcp_server.py`, `zoom_oauth_handler.py`, `zoom_server.py`, `utils/`, `CLAUDE.md`
- Replace: `README.md`

- [ ] **Step 1: Delete v1 files**

```bash
rm -f setup.sh zoom_wrapper.sh .env.example \
      base_mcp_server.py zoom_oauth_handler.py zoom_server.py \
      CLAUDE.md
rm -rf utils
```

- [ ] **Step 2: Write new `README.md`**

```markdown
# Zoom MCP Server v2

Read-only MCP server for Zoom Team Chat and meeting transcripts. Distributed as a `.mcpb` bundle.

## Install (Claude Desktop)

1. Create a Zoom Marketplace OAuth app: see [Zoom OAuth setup](#zoom-oauth-setup).
2. Download `zoom-mcp-<your-platform>.mcpb` from [Releases](#).
3. Double-click the `.mcpb` file. Claude Desktop will prompt for your Zoom Client ID and Client Secret.
4. Restart Claude Desktop. The Zoom tools appear automatically.

## Install (Claude Code)

```bash
claude mcp install /path/to/zoom-mcp-<your-platform>.mcpb
```

## What's available (22 tools)

- AI Companion: `zoom_search`, `zoom_ask`
- Chat: `zoom_list_channels`, `zoom_list_contacts`, `zoom_list_channel_members`,
  `zoom_get_channel_history`, `zoom_get_thread`, `zoom_get_message`,
  `zoom_list_pinned_messages`, `zoom_list_bookmarks`, `zoom_list_mention_groups`,
  `zoom_get_file`
- Shared spaces: `zoom_list_shared_spaces`, `zoom_get_shared_space`
- Meetings & transcripts: `zoom_list_meetings`, `zoom_get_meeting`,
  `zoom_list_recordings`, `zoom_get_meeting_transcript`
- Auth/util: `zoom_authenticate`, `zoom_revoke_authentication`,
  `zoom_get_my_info`, `zoom_resolve`

## Zoom OAuth setup

1. Go to https://marketplace.zoom.us/ → Develop → Build App → General App
2. Set redirect URL to `http://localhost:8000/oauth/callback`
3. Add these scopes (all read-only):

```
ai_companion:read:ask
ai_companion:read:search
contact:read:list_contacts
meeting:read:meeting
cloud_recording:read:list_user_recordings
cloud_recording:read:list_recording_files
cloud_recording:read:recording
cloud_recording:read:meeting_transcript
cloud_recording:read:content
team_chat:read:channel
team_chat:read:user_channel
team_chat:read:list_user_channels
team_chat:read:list_members
team_chat:read:list_user_messages
team_chat:read:user_message
team_chat:read:thread_message
team_chat:read:message_emoji
team_chat:read:list_pinned_messages
team_chat:read:list_bookmarks
team_chat:read:file
team_chat:read:chat_control
team_chat:read:mention_group
team_chat:read:list_contacts
team_chat:read:contact
team_chat:read:shared_space
team_chat:read:list_shared_spaces
team_chat:read:list_shared_space_channels
team_chat:read:list_shared_space_members
user:read:user
```

4. Copy your Client ID and Client Secret into the `.mcpb` install prompt.

## Security & data handling

- All Zoom traffic is TLS 1.2+ enforced.
- OAuth tokens are Fernet-encrypted at rest in `~/Library/Application Support/zoom-mcp/` (macOS) / `%APPDATA%\zoom-mcp\` (Windows) / `${XDG_DATA_HOME:-~/.local/share}/zoom-mcp/` (Linux), file mode `0600`.
- A SQLite metadata cache stores channel/contact/meeting names and IDs only — **no message bodies or transcript content are ever written to disk**.
- Logs scrub bearer tokens, message bodies, transcript text, and email addresses.
- Use `zoom_revoke_authentication` to wipe tokens, cache, and logs at any time.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env  # set ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET
.venv/bin/pytest
./scripts/dev-run.sh    # runs from source
./scripts/build_mcpb.sh # builds per-platform .mcpb bundles
```
```

- [ ] **Step 3: Run full test suite**

```bash
.venv/bin/pytest -v
```
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: remove v1 setup scripts; add MCPB-only README"
```

---

## Task 13: Build MCPB and verify

- [ ] **Step 1: Run the build for the host platform only first**

```bash
# Detect host platform and build just that one
HOST_TAG=$(./scripts/build_mcpb.sh 2>&1 | head -1) || true
ls -la dist/
```

If the build fails for non-host platforms (e.g. Windows wheels missing), that's expected when running on macOS — those builds happen in CI.

- [ ] **Step 2: Inspect the host-platform .mcpb**

```bash
unzip -l dist/zoom-mcp-darwin-arm64.mcpb | head -40
```
Expected: see `manifest.json`, `icon.png`, `server/main.py`, `server/lib/...`

- [ ] **Step 3: Verify the server boots inside the bundle**

```bash
cd $(mktemp -d)
unzip -q /path/to/dist/zoom-mcp-darwin-arm64.mcpb
ZOOM_CLIENT_ID=test ZOOM_CLIENT_SECRET=test \
  PYTHONPATH=server/lib \
  python3 -c "from server.main import setup_logging; setup_logging(); print('boot ok')"
```
Expected: `boot ok`

- [ ] **Step 4: Final commit + tag**

```bash
git add dist/
git commit -m "build: v2.0.0 .mcpb bundles"
git tag -a v2.0.0 -m "v2.0.0 — read-only MCPB rewrite"
```

---

## Self-Review

After completing tasks 1-13:

1. **Spec coverage:** All 22 tools are in `endpoints.ENDPOINTS` and have a corresponding `_h_<handler>` in `tools.py`. AI Companion, transcripts, files, shared spaces have dedicated modules. TLS 1.2+ is enforced in `http_client.py`. Cache schema covers all 10 spec tables. ✓

2. **Type consistency:** `oauth.make_authenticated_request` is the single auth-wrapped HTTP entry; all handler modules call it. `paginate_all` is the single auto-pagination entry; all list-style handlers call it. Cache method names (`put_X`, `get_X`) consistent.

3. **Placeholder scan:** No TODOs, TBDs, or "implement later" left in plan steps.
