# Zoom MCP Server v2 — Design

**Status:** Draft for review
**Author:** Alex Craig (with Claude)
**Date:** 2026-05-10
**Supersedes:** v1 (current `main`)

---

## 1. Goals

1. **Reliable cross-channel message search** — the v1 endpoint requires per-channel scoping; this is the primary user pain point.
2. **Easy meeting transcript retrieval** — pull transcripts for past meetings on demand, ready for summarisation.
3. **Easy onboarding** — single-file MCPB install for both Claude Code and Claude Desktop. No bash wrappers, no `setup.sh`, no `~/.claude.json` editing.
4. **Read-only by design** — no write/admin tools; minimum-necessary OAuth scopes; reduces consent friction and blast radius.
5. **Zoom Marketplace security compliance** — TLS 1.2+ enforced, transparent data-handling disclosure, no on-disk storage of message or transcript content.

## 2. Non-Goals

- Sending messages, reactions, edits, deletes
- Channel/contact/membership administration
- Real-time updates via webhooks (deferred; would require x-zm-signature handling)
- A local full-text index of every message (deferred; live parallel search is sufficient at expected scale)
- Backwards compatibility with v1 token storage or v1 setup paths

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      MCP host                                │
│   (Claude Desktop / Claude Code via stdio)                   │
└────────────────────────────┬────────────────────────────────┘
                             │ JSON-RPC over stdio
┌────────────────────────────▼────────────────────────────────┐
│  server/main.py — entry point                                │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  tools.py — registers tools, routes call_tool          │ │
│  └─┬───────────────────┬───────────────────┬──────────────┘ │
│    │                   │                   │                │
│  ┌─▼──────────┐  ┌─────▼──────┐  ┌────────▼───────┐         │
│  │ endpoints/ │  │  search.py │  │  transcripts.py │         │
│  │ dispatcher │  │  (fanout)  │  │  (VTT parser)   │         │
│  └─┬──────────┘  └────┬───────┘  └────────┬───────┘         │
│    │                  │                   │                  │
│  ┌─▼──────────────────▼───────────────────▼────────────────┐ │
│  │  http_client.py — shared httpx, TLS 1.2+, retries       │ │
│  └─┬──────────────────────────────────────────────────────┘ │
│    │                                                         │
│  ┌─▼──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ oauth.py       │  │ cache/store  │  │ paths.py     │     │
│  │ Fernet tokens  │  │ SQLite TTLs  │  │ OS-aware dirs│     │
│  └────────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
                             │ HTTPS (TLS 1.2+)
                             ▼
                    api.zoom.us / zoom.us/oauth
```

## 4. Module Layout

```
zoom-mcp-server/
├── manifest.json                  # MCPB manifest
├── icon.png
├── README.md
├── requirements.txt               # Authoritative dep list (used by build script)
├── server/
│   ├── __init__.py
│   ├── main.py                    # Entry point — replaces v1 zoom_server.py
│   ├── endpoints.py               # Declarative ENDPOINTS route table (chat + meetings)
│   ├── dispatcher.py              # Generic API dispatch + auto-pagination helper
│   ├── search.py                  # Cross-channel search (parallel fan-out)
│   ├── transcripts.py             # Recording manifest fetch + VTT parser
│   ├── tools.py                   # Tool registration / call_tool routing
│   ├── http_client.py             # Single shared httpx client + retry wrapper
│   ├── oauth.py                   # ZoomOAuthHandler (refactored)
│   ├── cache/
│   │   ├── __init__.py
│   │   ├── store.py               # SQLite-backed metadata cache
│   │   └── schema.py              # CREATE TABLE statements + migrations
│   ├── paths.py                   # Cross-platform user-data/log dir resolution
│   └── log_filter.py              # Sensitive-field scrubber for log records
├── scripts/
│   ├── build_mcpb.sh              # Builds 4 platform-specific .mcpb files
│   └── dev-run.sh                 # Run from source for local iteration
├── tests/
│   ├── test_cache.py
│   ├── test_dispatcher.py
│   ├── test_search.py
│   ├── test_transcripts.py
│   ├── test_paths.py
│   └── test_log_filter.py
├── docs/
│   └── superpowers/specs/
│       └── 2026-05-10-zoom-mcp-v2-design.md  (this file)
└── (NO setup.sh, zoom_wrapper.sh, .env.example, base_mcp_server.py at root)
```

## 5. Tool Surface (read-only, 14 tools)

| Tool | Purpose | Cached? |
|---|---|---|
| `zoom_authenticate` | Trigger OAuth flow (browser) | — |
| `zoom_revoke_authentication` | Wipe tokens, cache, logs | — |
| `zoom_get_my_info` | Authenticated user info | yes (in-memory only, 24h) |
| `zoom_resolve` | Resolve name/email to channel/contact/user ID | cache-backed |
| `zoom_list_channels` | Cache-first list of channels user belongs to | yes (1h) |
| `zoom_list_contacts` | Cache-first contacts list | yes (24h) |
| `zoom_list_channel_members` | Members of a channel | yes (1h) |
| `zoom_get_channel_history` | Auto-paginated message history; takes name or ID; date range; max_messages | always live |
| `zoom_search_all_messages` | Cross-channel search with parallel fan-out | always live |
| `zoom_list_pinned_messages` | Pinned messages in a channel | yes (5min) |
| `zoom_list_bookmarks` | User's bookmarked messages | yes (5min) |
| `zoom_list_meetings` | Past + upcoming meetings; filter by date/topic/participant | metadata cached |
| `zoom_get_meeting` | Meeting details, participant list, recording-files manifest | metadata cached |
| `zoom_get_meeting_transcript` | Download + parse transcript (VTT → text); never persisted | live, never cached |

### 5.1 Tool argument shapes

All tools accept human-friendly identifiers where possible:
- `channel`: name OR ID (resolved via cache)
- `contact`: email OR ID
- Date arguments: ISO-8601 strings
- Cache-backed list tools (`zoom_list_channels`, `zoom_list_contacts`, `zoom_list_channel_members`, `zoom_list_pinned_messages`, `zoom_list_bookmarks`, `zoom_list_meetings`) accept `force_refresh: bool = false` to bypass cache. Live-only tools (`zoom_get_channel_history`, `zoom_search_all_messages`, `zoom_get_meeting_transcript`) do not.

## 6. Cache Schema (SQLite)

Every table has `cached_at INTEGER NOT NULL` (Unix ms) for TTL eviction.

```sql
CREATE TABLE channels (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  type          INTEGER,
  member_count  INTEGER,
  jid           TEXT,
  channel_url   TEXT,
  cached_at     INTEGER NOT NULL
);
CREATE INDEX idx_channels_name ON channels(name);

CREATE TABLE contacts (
  id              TEXT PRIMARY KEY,
  email           TEXT NOT NULL,
  display_name    TEXT,
  dept            TEXT,
  presence_status TEXT,
  cached_at       INTEGER NOT NULL
);
CREATE INDEX idx_contacts_email ON contacts(email);
CREATE INDEX idx_contacts_name  ON contacts(display_name);

CREATE TABLE email_to_id (
  email      TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL,
  cached_at  INTEGER NOT NULL
);

CREATE TABLE channel_members (
  channel_id  TEXT NOT NULL,
  user_id     TEXT NOT NULL,
  role        TEXT,
  cached_at   INTEGER NOT NULL,
  PRIMARY KEY (channel_id, user_id)
);

CREATE TABLE meetings (
  id              TEXT PRIMARY KEY,
  uuid            TEXT,
  topic           TEXT,
  start_time      TEXT,
  duration        INTEGER,
  host_id         TEXT,
  has_recording   INTEGER,
  cached_at       INTEGER NOT NULL
);
CREATE INDEX idx_meetings_start ON meetings(start_time);
CREATE INDEX idx_meetings_topic ON meetings(topic);

CREATE TABLE meeting_files (
  meeting_id      TEXT NOT NULL,
  file_id         TEXT NOT NULL,
  file_type       TEXT,
  file_size       INTEGER,
  recording_start TEXT,
  cached_at       INTEGER NOT NULL,
  PRIMARY KEY (meeting_id, file_id)
);
-- NOTE: download_url is intentionally NOT stored. URLs are pre-signed and expire.
```

### 6.1 What is NOT cached on disk

| Item | Reason |
|---|---|
| Message bodies / text | Sensitive content; live fetch only |
| Transcript text | Sensitive content; live fetch + VTT parse only |
| Pre-signed download URLs | Time-limited credentials |
| Phone numbers, addresses | PII beyond what is necessary |
| Search query strings | User-confidential intent |

### 6.2 TTL Policy

| Table | TTL | Rationale |
|---|---|---|
| `email_to_id` | 30 days | User IDs don't change in practice |
| `channels` | 1 hour | Joins/leaves are infrequent |
| `contacts` | 24 hours | Directory changes slowly |
| `channel_members` | 1 hour | Membership changes occasionally |
| `meetings` (past) | 7 days | Past meetings are immutable |
| `meetings` (upcoming) | 15 minutes | Schedules change frequently |

### 6.3 Encryption

- **Tokens:** Fernet-encrypted (existing v1 approach), key in adjacent file at `0600`.
- **Cache DB:** Plain SQLite at `0600` in user data dir. SQLCipher rejected for MCPB cross-platform packaging difficulty (C extensions). Threat-model: an attacker with read access to the user-data dir already has the active session via the (encrypted) token; the cache provides marginal additional context (channel names, emails) and zero message content.

## 7. Storage Layout (cross-platform, MCPB-compatible)

| Path | macOS | Linux | Windows |
|---|---|---|---|
| User-data dir | `~/Library/Application Support/zoom-mcp/` | `${XDG_DATA_HOME:-~/.local/share}/zoom-mcp/` | `%APPDATA%\zoom-mcp\` |
| Log dir | `~/Library/Logs/zoom-mcp/` | `${XDG_STATE_HOME:-~/.local/state}/zoom-mcp/` | `%APPDATA%\zoom-mcp\logs\` |

Files inside user-data dir:

```
zoom-mcp/
├── tokens.enc      # Fernet-encrypted OAuth tokens
├── tokens.key      # Fernet key (mode 0600)
├── cache.sqlite    # Metadata cache (mode 0600)
└── cache.sqlite-wal, cache.sqlite-shm  # SQLite WAL files
```

`paths.py` is a small (~50 lines, no deps) module that resolves these per-platform.

**Nothing is ever written inside the MCPB bundle.** The bundle is read-only after install.

## 8. Cross-Channel Search (`zoom_search_all_messages`)

### 8.1 Algorithm

```
async def search_all_messages(query, from_date=None, to_date=None,
                              channel_filter=None, max_results=100):
    channels = await cache.get_channels(refresh_if_stale=True)
    contacts = await cache.get_contacts(refresh_if_stale=True)

    if channel_filter:
        channels = [c for c in channels if matches(c.name, channel_filter)]

    sem = asyncio.Semaphore(20)
    tasks = []

    for c in channels:
        tasks.append(_search_one(sem, to_channel=c.id, query=query,
                                 from_date=from_date, to_date=to_date))
    for ct in contacts:
        tasks.append(_search_one(sem, to_contact=ct.id, query=query,
                                 from_date=from_date, to_date=to_date))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    merged = []
    errors = 0
    for r in results:
        if isinstance(r, Exception):
            errors += 1
            continue
        merged.extend(r)

    merged.sort(key=lambda m: m["timestamp"], reverse=True)
    return {
        "results": merged[:max_results],
        "total_found": len(merged),
        "scopes_searched": len(tasks),
        "scopes_errored": errors,
    }
```

### 8.2 Per-call retry policy

Inherits from `http_client.py` unified policy (see Section 11).

### 8.3 Performance budget

| Channel count | Expected wall-time |
|---|---|
| 50  | ~1.5s |
| 200 | ~3s   |
| 500 | ~7s   |

Concurrency is `Semaphore(20)`; the 80-req/sec Zoom rate limit is the bottleneck above ~400 channels.

### 8.4 Edge cases

- Empty `query` → reject with clear error.
- Stale or empty cache → refresh first.
- Per-call timeout (10s connect / 30s total) → counts as error, search continues.
- Some channels may return 403 (private, no access); logged and skipped.
- First page only per scope (50 results max); user can drill into a specific channel via `zoom_get_channel_history` for more depth.

## 9. Meeting Transcript Retrieval (`zoom_get_meeting_transcript`)

### 9.1 Flow

```
1. GET /meetings/{id}/recordings  (or by UUID)
2. Locate file_type=TRANSCRIPT in recording_files[]; fall back to file_type=CC.
3. GET <download_url> with Authorization: Bearer <access_token>
   - Stream response; abort if Content-Length > 50MB.
4. Parse VTT → plain text with [HH:MM] speaker tags using the inline parser.
5. Return text content.
6. Discard download URL, transcript bytes.
```

### 9.2 VTT parser

Inline ~30 lines, no external deps. Handles:
- Standard `00:00:00.000 --> 00:00:05.000\n<v Speaker Name>Text` blocks
- Plain `00:00:00.000 --> 00:00:05.000\nText` blocks (no speaker tag)
- WEBVTT header line, NOTE blocks, empty lines

Output format:
```
[00:00] Speaker Name: Text...
[00:05] Speaker Name: Continuing...
```

### 9.3 Failure modes

| Condition | Response |
|---|---|
| No recording for meeting | "No recording exists for this meeting." |
| Recording exists, no TRANSCRIPT file | "Recording exists but transcript was not generated. Free Zoom plans do not include transcription." |
| Transcript still processing | "Transcript is still being generated. Try again in a few minutes." |
| Pre-signed URL expired | Refresh recording manifest, retry once; then surface error. |
| VTT parse failure | Return raw text content with a parse-warning note. |
| File size > 50MB | Refuse; suggest the user fetch via Zoom web UI directly. |

## 10. Auto-Pagination Helper

`dispatcher.py` exposes `paginate_all(method, url, params, max_items=None)` which:
1. Sends initial request with `page_size=100` (or 50 where API caps lower).
2. While `next_page_token` is non-empty and `len(items) < max_items`: send next page.
3. Returns merged list, or stops at `max_items`.
4. Used by: `zoom_list_channels`, `zoom_list_contacts`, `zoom_list_channel_members`, `zoom_get_channel_history`, `zoom_list_meetings`, `zoom_list_pinned_messages`, `zoom_list_bookmarks`.

`max_items` defaults to 1000 to prevent runaway loops; tools can raise the cap (e.g. `get_channel_history` defaults to 500).

## 11. HTTP Client & Retry Policy

```python
ssl_ctx = ssl.create_default_context()
ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_2

CLIENT = httpx.AsyncClient(
    verify=ssl_ctx,
    timeout=httpx.Timeout(30.0, connect=10.0),
    limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
    headers={"User-Agent": "zoom-mcp/2.0"},
)
```

Retry wrapper applied to every Zoom API call:

| Status / error | Action |
|---|---|
| `200 / 201 / 204` | Return |
| `401` | Refresh token, retry once. If still 401, re-prompt OAuth. |
| `429` | Sleep `Retry-After` seconds (default 30); retry up to 3x |
| `5xx` | Exponential backoff (1s, 2s, 4s); retry up to 3x |
| Network error / timeout | Exp backoff, retry up to 3x |
| `4xx` other | No retry; surface error to caller |

OAuth-authenticated requests (currently bypass v1 retry logic at `utils/oauth_handler.py:294`) MUST go through this wrapper in v2.

## 12. OAuth Scopes (read-only minimum)

```
chat_message:read
chat_channel:read
chat_contact:read   (or contact:read if marketplace requires)
user:read
cloud_recording:read
meeting:read
```

Removed from v1: `chat_message:write`, `chat_channel:write`.

The README and the MCPB `long_description` will explicitly list these scopes so the user can copy them into their Zoom Marketplace app config.

## 13. Security & Compliance

### 13.1 Zoom Marketplace security questions

| Question | Answer | Implementation |
|---|---|---|
| TLS 1.2+ for all network traffic? | **Yes** | `ssl_ctx.minimum_version = TLSv1_2` on shared httpx client; verified by integration test that asserts `ssl_version >= TLSv1_2` against `api.zoom.us`. |
| Webhook signature verification (x-zm-signature)? | **N/A — no webhooks** | Documented in README; if webhooks are added later, they MUST verify via HMAC-SHA256 of `v0:{ts}:{body}` with the verification token. |
| Collect/store/log/retain Zoom user data inc. OAuth tokens? | **Yes — locally only** | Tokens Fernet-encrypted at 0600; cache stores metadata only (no message/transcript content); nothing transmitted to any third party; `zoom_revoke_authentication` wipes everything. |

### 13.2 Logging policy

`log_filter.py` is a `logging.Filter` that scrubs the following from every log record's `msg` and `args`:
- Bearer tokens (`Authorization: Bearer ...` → `Bearer [redacted]`)
- Refresh tokens (regex on `refresh_token` key in dicts)
- Message bodies in any field named `message`, `text`, `body`, `content`, `transcript`
- URL query parameters: `search_key`, `code` (auth code), `email`
- Email addresses in path segments (best-effort regex)

Logs include: tool name, duration, HTTP status code, Zoom request ID from response headers, error type.

### 13.3 Threat model

| Threat | Mitigation |
|---|---|
| Filesystem read by unprivileged user on the host | Tokens encrypted at rest; data dir at `0600`; cache contains metadata only. |
| Filesystem read by privileged attacker (root) | Out of scope — not defended. |
| Token theft via memory dump | Out of scope — same constraints as any local OAuth client. |
| Network-level eavesdrop | TLS 1.2+ enforced; cert verification on. |
| Malicious MCPB tampering | MCPB integrity is the host's responsibility (Claude Desktop verifies signature where available). |
| Prompt injection via message content | Tools return raw API content unmodified; downstream model is responsible. We do NOT execute, eval, or render embedded HTML/links. |

### 13.4 Data lifecycle

- **Tokens:** persist until manual revocation or token-server rejection.
- **Cache:** TTL-evicted on read; full DB wiped by `zoom_revoke_authentication`.
- **Message bodies:** never persisted; fetched, returned to MCP client, discarded from server memory.
- **Transcripts:** never persisted; fetched, parsed, returned, discarded.
- **Logs:** rotated at 10MB × 5 files (50MB cap); contain no message or transcript content.

## 14. MCPB Packaging

### 14.1 Bundle layout

```
zoom-team-chat-search-<platform>.mcpb (zip)
├── manifest.json
├── icon.png
├── server/                    # Python source (read-only after install)
└── lib/python/                # Bundled platform-specific wheels
```

### 14.2 manifest.json

```json
{
  "dxt_version": "0.1",
  "name": "zoom-team-chat-search",
  "display_name": "Zoom Team Chat & Transcripts",
  "version": "2.0.0",
  "description": "Read-only search across Zoom Team Chat messages and meeting transcripts.",
  "author": {"name": "Alex Craig"},
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
        "PYTHONPATH":         "${__dirname}/lib/python"
      }
    }
  },
  "tools": [/* generated from endpoints.py at build time */],
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
      "default": "http://localhost:8000/oauth/callback"
    }
  },
  "compatibility": {
    "platforms": ["darwin", "win32", "linux"],
    "runtimes": {"python": ">=3.10"}
  }
}
```

### 14.3 Build script

`scripts/build_mcpb.sh` produces 4 platform-specific `.mcpb` files by:

```bash
for platform in darwin-arm64 darwin-x64 manylinux_2_17_x86_64 win_amd64; do
  rm -rf build/lib/python && mkdir -p build/lib/python
  pip download \
    --platform "$platform" \
    --python-version 3.11 \
    --only-binary :all: \
    -d build/lib/python \
    -r requirements.txt
  # unpack wheels into lib/python flat layout
  for whl in build/lib/python/*.whl; do
    unzip -qo "$whl" -d build/lib/python && rm "$whl"
  done
  cp -r server icon.png manifest.json build/
  (cd build && zip -qr "../dist/zoom-mcp-${platform}.mcpb" .)
done
```

### 14.4 Dependencies

- **Pure Python:** `mcp`, `httpx`, `httpcore`, `anyio`, `sniffio`, `idna`, `certifi` — no platform variants needed.
- **Native:** `cryptography` (C-ext), `pydantic-core` (Rust ext via `pydantic`) — require platform-specific wheels.
- **Dropped from v1:** `python-dotenv` (env vars come from manifest).

`requirements.txt` is the single source of truth and is the input to the build script.

### 14.5 Why per-platform .mcpb files

We considered: (a) single bundle with all platform wheels included, (b) install-on-first-run, (c) pure-Python re-implementation of Fernet using stdlib only.

(a) bloats every install; (b) breaks offline-install assumption; (c) is technically possible but introduces custom crypto code — high-risk, rejected. Per-platform builds are standard practice for Python MCPBs and the build script ships ready-made.

## 15. Removed in v2

| File | Reason |
|---|---|
| `setup.sh` | Replaced by MCPB install |
| `zoom_wrapper.sh` | No bash wrapper needed |
| `.env.example` | Config comes from MCPB user_config |
| `base_mcp_server.py` (root) | Refactored into `server/` modules |
| `zoom_oauth_handler.py` (root) | Moved to `server/oauth.py` |
| `utils/__init__.py`, `utils/oauth_handler.py`, `utils/token_manager.py` | Refactored under `server/` |
| Self-installing CLAUDE.md flow | Replaced by README pointing at MCPB releases |

## 16. Testing Strategy

| Layer | What | How |
|---|---|---|
| Unit | VTT parser | Sample VTT fixtures, including malformed |
| Unit | Cache TTL eviction | Time-travel via injected clock |
| Unit | Path resolver | Mocked platform.system + env vars |
| Unit | Log filter scrubber | Inputs with tokens / message bodies; assert redaction |
| Unit | Auto-paginator | Mock httpx with synthetic next_page_tokens |
| Unit | Retry wrapper | Mock httpx returning 429/5xx sequences |
| Integration | OAuth flow | mock Zoom token endpoint via local httpx mock |
| Integration | TLS minimum version | live call to api.zoom.us, assert TLSv1_2+ |
| Integration | Cross-channel search | mocked Zoom API with N synthetic channels |
| Smoke (manual) | End-to-end MCPB install on macOS, Linux, Windows | manual test plan in `docs/release-checklist.md` |

## 17. Migration from v1

- Existing v1 token files (`<repo>/tokens/`) are NOT migrated. v2 forces a fresh OAuth on first install — security-cleaner.
- Users with v1 in `~/.claude.json` should remove that entry manually; a one-shot `scripts/cleanup-v1.sh` is provided for convenience.
- Version bump to `2.0.0` reflects breaking changes in tool surface, distribution, and storage paths.

## 18. Open Questions

None at design time. Items deferred for future work but not blocking this design:
- Local FTS5 message index (Approach B from brainstorming) if live parallel search proves too slow at >500 channels.
- Webhook receiver for real-time updates (would require x-zm-signature verification path).
- macOS Keychain / Windows Credential Vault integration for tokens (replaces Fernet+key-file).
