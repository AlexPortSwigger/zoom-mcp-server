"""SQLite-backed metadata cache with TTL eviction.

No message bodies, no transcript content, no pre-signed URLs are persisted.

Connection management notes (v2.2.9):

Claude Desktop spawns multiple short-lived MCP server instances at
startup as part of its connector probing — typically 2-3 transient
processes alongside the real one. Each previously opened SQLite in
WAL mode at construction time, and the WAL pragma needs a brief
exclusive lock; if a transient instance held the lock when a real
instance tried to start, the real instance crashed with
``sqlite3.OperationalError: database is locked`` on a fresh install.

Two changes fix this:

1. *Lazy connection*: the constructor no longer opens SQLite. The
   first method call does. Transient instances never touch the cache
   file (they exit before any tool call), so the race window closes.

2. *Defensive WAL pragma*: when we do open the connection we set
   ``busy_timeout`` first so SQLite waits for transient locks rather
   than failing immediately, and the WAL pragma itself is wrapped in
   a short retry loop. If WAL still can't be enabled we fall back to
   the default journal mode rather than crashing — the cache is a
   metadata-only convenience layer, not load-bearing.
"""
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .schema import apply_schema

_logger = logging.getLogger("zoom-mcp")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _open_sqlite_with_wal(db_path: Path) -> sqlite3.Connection:
    """Open the SQLite cache with WAL + busy timeout, retrying on the
    WAL pragma if a transient lock blocks it. Falls back to the default
    journal mode rather than crashing if WAL really can't be enabled."""
    conn = sqlite3.connect(
        db_path,
        isolation_level=None,
        timeout=10.0,  # also: SQLite-level busy wait
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000;")  # 10s on every statement
    last_err: Optional[Exception] = None
    for attempt in range(5):
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            last_err = None
            break
        except sqlite3.OperationalError as e:
            last_err = e
            time.sleep(0.2 * (attempt + 1))
    if last_err is not None:
        _logger.warning(
            "Could not enable SQLite WAL after retries (%s); falling "
            "back to default journal mode. Cache will work but with "
            "lower concurrency.", last_err,
        )
    conn.execute("PRAGMA synchronous=NORMAL;")
    apply_schema(conn)
    if os.name == "posix":
        try:
            os.chmod(db_path, 0o600)
        except OSError:
            pass
    return conn


class CacheStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Lazy: don't open SQLite until first use. Lets Claude Desktop's
        # transient probe instances exit cleanly without touching the
        # database file (which is what was triggering the WAL race on
        # fresh installs — see module docstring).
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = _open_sqlite_with_wal(self.db_path)
        return self._conn

    # --- channels ---

    def put_channels(self, channels: Iterable[Dict[str, Any]]) -> None:
        ts = _now_ms()
        rows = [
            (
                c["id"], c["name"], c.get("type"), c.get("member_count"),
                c.get("jid"), c.get("channel_url"),
                1 if c.get("starred") else 0, ts,
            )
            for c in channels
        ]
        self.conn.executemany(
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
        params: List[Any] = [cutoff]
        if starred_only:
            sql += " AND starred = 1"
        sql += " ORDER BY name"
        return [dict(r) for r in self.conn.execute(sql, params)]

    def get_channel_by_id(self, channel_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM channels WHERE id = ?", (channel_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_channel_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM channels WHERE name = ? LIMIT 1", (name,)
        ).fetchone()
        return dict(row) if row else None

    # --- contacts ---

    def put_contacts(self, contacts: Iterable[Dict[str, Any]]) -> None:
        ts = _now_ms()
        rows = []
        for c in contacts:
            # Zoom returns first_name + last_name on contacts; some
            # responses also include "name" or "display_name". Build a
            # display string from whichever is available.
            display = (
                c.get("display_name")
                or c.get("name")
                or " ".join(
                    p for p in [c.get("first_name"), c.get("last_name")] if p
                )
                or c.get("email", "")
            )
            rows.append(
                (
                    c["id"],
                    c.get("email", ""),
                    display,
                    c.get("dept"),
                    c.get("presence_status"),
                    ts,
                )
            )
        self.conn.executemany(
            "INSERT OR REPLACE INTO contacts "
            "(id, email, display_name, dept, presence_status, cached_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )

    def get_contacts(self, ttl_seconds: int = 86400) -> List[Dict[str, Any]]:
        cutoff = _now_ms() - ttl_seconds * 1000
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM contacts WHERE cached_at >= ? ORDER BY display_name",
                (cutoff,),
            )
        ]

    def get_contact_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM contacts WHERE email = ? LIMIT 1", (email,),
        ).fetchone()
        return dict(row) if row else None

    # --- email -> id ---

    def put_email_to_id(self, email: str, user_id: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO email_to_id (email, user_id, cached_at) VALUES (?, ?, ?)",
            (email, user_id, _now_ms()),
        )

    def get_user_id_by_email(
        self, email: str, ttl_seconds: int = 30 * 86400
    ) -> Optional[str]:
        cutoff = _now_ms() - ttl_seconds * 1000
        row = self.conn.execute(
            "SELECT user_id FROM email_to_id WHERE email = ? AND cached_at >= ?",
            (email, cutoff),
        ).fetchone()
        return row["user_id"] if row else None

    # --- channel members ---

    def put_channel_members(
        self, channel_id: str, members: Iterable[Dict[str, Any]]
    ) -> None:
        ts = _now_ms()
        self.conn.execute(
            "DELETE FROM channel_members WHERE channel_id = ?", (channel_id,),
        )
        rows = [(channel_id, m["id"], m.get("role"), ts) for m in members]
        self.conn.executemany(
            "INSERT INTO channel_members (channel_id, user_id, role, cached_at) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )

    def get_channel_members(
        self, channel_id: str, ttl_seconds: int = 3600
    ) -> List[Dict[str, Any]]:
        cutoff = _now_ms() - ttl_seconds * 1000
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM channel_members WHERE channel_id = ? AND cached_at >= ?",
                (channel_id, cutoff),
            )
        ]

    # --- meetings ---

    def put_meetings(self, meetings: Iterable[Dict[str, Any]]) -> None:
        ts = _now_ms()
        rows = [
            (
                m["id"], m.get("uuid"), m.get("topic"), m.get("start_time"),
                m.get("duration"), m.get("host_id"),
                1 if m.get("has_recording") else 0, ts,
            )
            for m in meetings
        ]
        self.conn.executemany(
            "INSERT OR REPLACE INTO meetings "
            "(id, uuid, topic, start_time, duration, host_id, has_recording, cached_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    def get_meeting(self, meeting_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM meetings WHERE id = ?", (meeting_id,),
        ).fetchone()
        return dict(row) if row else None

    # --- shared spaces ---

    def put_shared_spaces(self, spaces: Iterable[Dict[str, Any]]) -> None:
        ts = _now_ms()
        rows = [
            (
                s["id"], s.get("name", ""), s.get("member_count"),
                s.get("channel_count"), s.get("owner_id"), ts,
            )
            for s in spaces
        ]
        self.conn.executemany(
            "INSERT OR REPLACE INTO shared_spaces "
            "(id, name, member_count, channel_count, owner_id, cached_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )

    def get_shared_spaces(self, ttl_seconds: int = 3600) -> List[Dict[str, Any]]:
        cutoff = _now_ms() - ttl_seconds * 1000
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM shared_spaces WHERE cached_at >= ? ORDER BY name",
                (cutoff,),
            )
        ]

    # --- mention groups ---

    def put_mention_groups(
        self, channel_id: str, groups: Iterable[Dict[str, Any]]
    ) -> None:
        ts = _now_ms()
        self.conn.execute(
            "DELETE FROM mention_groups WHERE channel_id = ?", (channel_id,),
        )
        rows = [
            (channel_id, g["id"], g.get("name"), g.get("member_count"), ts)
            for g in groups
        ]
        self.conn.executemany(
            "INSERT INTO mention_groups "
            "(channel_id, group_id, name, member_count, cached_at) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )

    def get_mention_groups(
        self, channel_id: str, ttl_seconds: int = 3600
    ) -> List[Dict[str, Any]]:
        cutoff = _now_ms() - ttl_seconds * 1000
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM mention_groups WHERE channel_id = ? AND cached_at >= ?",
                (channel_id, cutoff),
            )
        ]

    # --- maintenance ---

    def clear_all(self) -> None:
        for table in (
            "channels", "contacts", "email_to_id", "channel_members",
            "meetings", "meeting_files", "shared_spaces",
            "shared_space_channels", "shared_space_members", "mention_groups",
        ):
            self.conn.execute(f"DELETE FROM {table}")

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
