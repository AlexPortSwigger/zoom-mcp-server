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
