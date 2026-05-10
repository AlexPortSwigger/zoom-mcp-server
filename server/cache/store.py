"""SQLite-backed metadata cache with TTL eviction.

No message bodies, no transcript content, no pre-signed URLs are persisted.
"""
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

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
            (
                c["id"], c["name"], c.get("type"), c.get("member_count"),
                c.get("jid"), c.get("channel_url"),
                1 if c.get("starred") else 0, ts,
            )
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
        params: List[Any] = [cutoff]
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
            (
                c["id"], c.get("email", ""), c.get("display_name"),
                c.get("dept"), c.get("presence_status"), ts,
            )
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
        return [
            dict(r)
            for r in self._conn.execute(
                "SELECT * FROM contacts WHERE cached_at >= ? ORDER BY display_name",
                (cutoff,),
            )
        ]

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

    def put_channel_members(
        self, channel_id: str, members: Iterable[Dict[str, Any]]
    ) -> None:
        ts = _now_ms()
        self._conn.execute(
            "DELETE FROM channel_members WHERE channel_id = ?", (channel_id,),
        )
        rows = [(channel_id, m["id"], m.get("role"), ts) for m in members]
        self._conn.executemany(
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
            for r in self._conn.execute(
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
        self._conn.executemany(
            "INSERT OR REPLACE INTO meetings "
            "(id, uuid, topic, start_time, duration, host_id, has_recording, cached_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
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
            (
                s["id"], s.get("name", ""), s.get("member_count"),
                s.get("channel_count"), s.get("owner_id"), ts,
            )
            for s in spaces
        ]
        self._conn.executemany(
            "INSERT OR REPLACE INTO shared_spaces "
            "(id, name, member_count, channel_count, owner_id, cached_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )

    def get_shared_spaces(self, ttl_seconds: int = 3600) -> List[Dict[str, Any]]:
        cutoff = _now_ms() - ttl_seconds * 1000
        return [
            dict(r)
            for r in self._conn.execute(
                "SELECT * FROM shared_spaces WHERE cached_at >= ? ORDER BY name",
                (cutoff,),
            )
        ]

    # --- mention groups ---

    def put_mention_groups(
        self, channel_id: str, groups: Iterable[Dict[str, Any]]
    ) -> None:
        ts = _now_ms()
        self._conn.execute(
            "DELETE FROM mention_groups WHERE channel_id = ?", (channel_id,),
        )
        rows = [
            (channel_id, g["id"], g.get("name"), g.get("member_count"), ts)
            for g in groups
        ]
        self._conn.executemany(
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
            for r in self._conn.execute(
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
            self._conn.execute(f"DELETE FROM {table}")

    def close(self) -> None:
        self._conn.close()
