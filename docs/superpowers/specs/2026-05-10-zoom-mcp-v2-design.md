# Zoom MCP Server v2 — Design

**Status:** Draft for review
**Author:** Alex Craig (with Claude)
**Date:** 2026-05-10
**Supersedes:** v1 (current `main`)

---

## 1. Goals

1. **AI-Companion-powered search and Q&A** — `zoom_search` and `zoom_ask` use Zoom's AI Companion endpoints to search and answer questions across Meetings/Chat/Docs in a single call with grounded citations. Replaces the originally planned manual fan-out.
2. **Easy meeting transcript retrieval** — pull transcripts for past meetings on demand, ready for summarisation.
3. **Easy onboarding** — single-file MCPB install for both Claude Code and Claude Desktop. No bash wrappers, no `setup.sh`, no `~/.claude.json` editing.
4. **Read-only by design** — no write/admin tools; minimum-necessary OAuth scopes; reduces consent friction and blast radius.
5. **Zoom Marketplace security compliance** — TLS 1.2+ enforced, transparent data-handling disclosure, no on-disk storage of message or transcript content.

## 2. Non-Goals

- Sending messages, reactions, edits, deletes
- Channel/contact/membership administration
- Real-time updates via webhooks (deferred; would require x-zm-signature handling)
- A local full-text index of every message (deferred; AI Companion search supersedes the original need)
- Manual parallel-fan-out cross-channel search (replaced by AI Companion search; revisit only if AI Companion proves insufficient for specific query types like exact-substring or regex)
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
│  │ endpoints/ │  │ ai_compan. │  │  transcripts.py │         │
│  │ dispatcher │  │ search/ask │  │  (VTT parser)   │         │
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
│   ├── ai_companion.py            # zoom_search & zoom_ask (AI Companion endpoints)
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
│   ├── test_ai_companion.py
│   ├── test_transcripts.py
│   ├── test_files.py            # zoom_get_file MIME-gate behaviour
│   ├── test_shared_spaces.py
│   ├── test_message_inline.py   # reactions + attachments + thread inline data
│   ├── test_mention_groups.py
│   ├── test_paths.py
│   └── test_log_filter.py
├── docs/
│   └── superpowers/specs/
│       └── 2026-05-10-zoom-mcp-v2-design.md  (this file)
└── (NO setup.sh, zoom_wrapper.sh, .env.example, base_mcp_server.py at root)
```

## 5. Tool Surface (read-only, 22 tools)

| # | Tool | Purpose | Cached? |
|---|---|---|---|
| 1 | `zoom_authenticate` | Trigger OAuth flow (browser) | — |
| 2 | `zoom_revoke_authentication` | Wipe tokens, cache, logs | — |
| 3 | `zoom_get_my_info` | Authenticated user info | yes (in-memory, 24h) |
| 4 | `zoom_resolve` | Resolve name/email to channel/contact/user ID | cache-backed |
| 5 | `zoom_search` | **AI Companion search** across Meetings/Chat/Docs | always live |
| 6 | `zoom_ask` | **AI Companion grounded Q&A** with citations | always live |
| 7 | `zoom_list_channels` | Channels user belongs to; includes `starred` field; `starred_only` filter | yes (1h) |
| 8 | `zoom_list_contacts` | User's contacts | yes (24h) |
| 9 | `zoom_list_channel_members` | Members of a channel | yes (1h) |
| 10 | `zoom_get_channel_history` | Auto-paginated raw history with reactions + attachment metadata inline | always live |
| 11 | `zoom_get_thread` | Messages under a thread, with reactions + attachments inline | always live |
| 12 | `zoom_get_message` | Single message lookup (citation drill-down) | always live |
| 13 | `zoom_get_file` | File metadata + text content for text/code files; metadata-only for binary | always live |
| 14 | `zoom_list_pinned_messages` | Pinned messages in a channel | yes (5min) |
| 15 | `zoom_list_bookmarks` | User's bookmarked messages | yes (5min) |
| 16 | `zoom_list_mention_groups` | Mention groups (`@engineering`-style) in a channel | yes (1h) |
| 17 | `zoom_list_shared_spaces` | Shared spaces user belongs to | yes (1h) |
| 18 | `zoom_get_shared_space` | Shared-space detail + channels + members (via `include` arg) | yes (1h) |
| 19 | `zoom_list_meetings` | List meetings (past + upcoming); filters: date range, topic, participant | metadata cached |
| 20 | `zoom_get_meeting` | Meeting detail incl. participant list and recording-files manifest | metadata cached |
| 21 | `zoom_list_recordings` | List user's cloud recordings | metadata cached |
| 22 | `zoom_get_meeting_transcript` | Download + parse transcript (VTT → text); never persisted on disk | live, never cached |

### 5.1 Tool argument shapes

All tools accept human-friendly identifiers where possible:
- `channel`: name OR ID (resolved via cache)
- `contact`: email OR ID
- Date arguments: ISO-8601 strings
- Cache-backed list tools accept `force_refresh: bool = false` to bypass cache. Live-only tools do not.

`zoom_search` and `zoom_ask` accept an optional `scope` argument: `"chat" | "meetings" | "docs" | "all"` (default `"all"`), and optional `from_date` / `to_date`.

### 5.2 Inline data on message responses

`zoom_get_channel_history`, `zoom_get_thread`, and `zoom_get_message` return each message with:

```json
{
  "message_id": "...",
  "sender": {"id": "...", "display_name": "...", "email": "..."},
  "timestamp": "2026-05-10T...",
  "text": "...",
  "reactions": [{"emoji": "👍", "count": 5, "users": ["...", "..."]}],
  "files":     [{"file_id": "...", "name": "report.pdf", "mime_type": "application/pdf", "size": 1234567, "download_url": "<expires soon>"}],
  "thread_parent_id": null,
  "edited": false,
  "deeplink": "https://..."
}
```

Reactions and `files` are populated when the corresponding scopes are granted. `download_url` is included only on file objects (never persisted to cache).

### 5.3 `zoom_get_file` behaviour

- Always returns metadata: `{file_id, name, mime_type, size, sender, posted_at, channel_id}`
- For text-like MIME types (`text/*`, `application/json`, `application/x-yaml`, `application/x-toml`, `application/xml`): downloads the file (capped at 1MB) and returns content under a `text` field.
- For all other types: returns metadata only with a one-shot `download_url`. v2 does NOT decode images, PDFs, archives, or office docs.
- Refuses to download files larger than 10MB even for text types.

### 5.4 Shared spaces

- `zoom_list_shared_spaces` returns `[{space_id, name, member_count, channel_count, owner_id}]`.
- `zoom_get_shared_space(space_id, include="all"|"detail"|"channels"|"members")` returns whichever combination of detail/channels/members is requested. Default `include="detail"`.

### 5.5 Mention groups

- `zoom_list_mention_groups(channel)` returns `[{group_id, name, member_count, members: [user_id, ...]}]`. Useful signal for "what teams are addressed in this channel".

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
  starred       INTEGER,        -- 0/1; from chat_control endpoint
  cached_at     INTEGER NOT NULL
);
CREATE INDEX idx_channels_name    ON channels(name);
CREATE INDEX idx_channels_starred ON channels(starred);

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

CREATE TABLE shared_spaces (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  member_count  INTEGER,
  channel_count INTEGER,
  owner_id      TEXT,
  cached_at     INTEGER NOT NULL
);

CREATE TABLE shared_space_channels (
  space_id    TEXT NOT NULL,
  channel_id  TEXT NOT NULL,
  cached_at   INTEGER NOT NULL,
  PRIMARY KEY (space_id, channel_id)
);

CREATE TABLE shared_space_members (
  space_id   TEXT NOT NULL,
  user_id    TEXT NOT NULL,
  role       TEXT,
  cached_at  INTEGER NOT NULL,
  PRIMARY KEY (space_id, user_id)
);

CREATE TABLE mention_groups (
  channel_id    TEXT NOT NULL,
  group_id      TEXT NOT NULL,
  name          TEXT,
  member_count  INTEGER,
  cached_at     INTEGER NOT NULL,
  PRIMARY KEY (channel_id, group_id)
);
```

### 6.1 What is NOT cached on disk

| Item | Reason |
|---|---|
| Message bodies / text | Sensitive content; live fetch only |
| Transcript text | Sensitive content; live fetch + VTT parse only |
| Attachment / file content (text or binary) | Sensitive; live fetch only via `zoom_get_file` |
| Pre-signed download URLs (recordings, attachments) | Time-limited credentials |
| Emoji-reaction details | Live with messages; not separately persisted |
| Phone numbers, addresses | PII beyond what is necessary |
| Search query strings + AI Companion answers | User-confidential intent and content |

### 6.2 TTL Policy

| Table | TTL | Rationale |
|---|---|---|
| `email_to_id` | 30 days | User IDs don't change in practice |
| `channels` | 1 hour | Joins/leaves and starred state change infrequently |
| `contacts` | 24 hours | Directory changes slowly |
| `channel_members` | 1 hour | Membership changes occasionally |
| `meetings` (past/recorded) | 7 days | Past meetings are immutable |
| `shared_spaces` | 1 hour | Org structure changes infrequently |
| `shared_space_channels` | 1 hour | Same as above |
| `shared_space_members` | 1 hour | Same as above |
| `mention_groups` | 1 hour | Org structure changes infrequently |

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

## 8. Search and Q&A via AI Companion

Both `zoom_search` and `zoom_ask` are thin wrappers around Zoom AI Companion endpoints (`ai_companion:read:search` and `ai_companion:read:ask`). This replaces the originally planned manual parallel fan-out — Zoom's server-side ranking is better, faster, and works across Meetings/Chat/Docs in one call.

### 8.1 `zoom_search`

```
zoom_search(query, scope="all", from_date=None, to_date=None, max_results=50)
  ↓
POST /ai_companion/search   (single API call)
  body: { "query": ..., "sources": [...], "from": ..., "to": ..., "limit": ... }
  ↓
Returns: [{source_type, source_id, title/topic, snippet, timestamp, relevance, deeplink}]
```

`scope` maps to AI Companion `sources` parameter:
- `"chat"`     → `["team_chat"]`
- `"meetings"` → `["meeting"]`
- `"docs"`     → `["zoom_doc"]`
- `"all"`      → `["team_chat", "meeting", "zoom_doc"]`

### 8.2 `zoom_ask`

```
zoom_ask(question, scope="all", from_date=None, to_date=None)
  ↓
POST /ai_companion/ask
  body: { "question": ..., "sources": [...], "from": ..., "to": ... }
  ↓
Returns: { "answer": "...", "citations": [{source_type, source_id, title, snippet, deeplink}, ...] }
```

The model-generated answer is returned verbatim; citations let Claude (or the user) drill into specific messages or meeting transcripts via `zoom_get_message`, `zoom_get_thread`, or `zoom_get_meeting_transcript`.

### 8.3 Performance & rate limits

Single API call replaces N parallel calls. Wall-time per query: ~1-3s including AI Companion processing. No per-channel concurrency tuning needed.

If AI Companion endpoints return 429 (organisation rate limit) or 503, the unified retry policy in §11 applies.

### 8.4 Failure modes

| Condition | Behaviour |
|---|---|
| AI Companion not enabled for the user/org | 403 from endpoint → return error message: "AI Companion is not enabled for this account. Ask your Zoom admin to enable it." |
| Empty query | Reject with clear error |
| `from_date > to_date` | Reject with clear error |
| 5xx / network error | Retry per §11 |
| 429 with Retry-After | Sleep and retry |

### 8.5 Why not also keep manual fan-out as a fallback

YAGNI. If AI Companion proves insufficient for a use case (e.g. exact-substring search, regex), we add a `zoom_search_classic` tool in v2.1. v2.0 ships AI Companion only.

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
4. Used by: `zoom_list_channels`, `zoom_list_contacts`, `zoom_list_channel_members`, `zoom_get_channel_history`, `zoom_list_recordings`, `zoom_list_pinned_messages`, `zoom_list_bookmarks`, `zoom_list_shared_spaces`, `zoom_get_shared_space`, `zoom_list_mention_groups`.

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

## 12. OAuth Scopes (granular, read-only)

The Zoom Marketplace app for v2 requests the following 28 granular scopes:

**AI Companion** (powers `zoom_search`, `zoom_ask`):
```
ai_companion:read:ask
ai_companion:read:search
```

**Contacts:**
```
contact:read:list_contacts
```

**Meetings:**
```
meeting:read:meeting
```

**Recordings & transcripts:**
```
cloud_recording:read:list_user_recordings
cloud_recording:read:list_recording_files
cloud_recording:read:recording
cloud_recording:read:meeting_transcript
cloud_recording:read:content
```

**Team Chat (read-only):**
```
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
```

**User:**
```
user:read:user
```

### 12.1 Scopes deliberately NOT requested

| Category | Why excluded |
|---|---|
| All `team_chat:write:*` and `team_chat:update:*` | Read-only design |
| `imchat:userapp` | Not building an in-client app |
| All `meeting:read:meeting_audio/video/chat/screenshare/transcript` | Real-time meeting integrations out of scope; cloud-recording transcripts cover the use case |
| `cloud_recording:read:recording_settings` | Recording settings not surfaced |
| `team_chat:read:invite_link`, `:list_invitations`, `:list_approvals`, `:list_reminders`, `:list_scheduled_messages` | Admin/personal-state features out of scope |
| `team_chat:read:list_custom_emojis`, `:archive_channels`, `:list_user_sessions` | Low value |

The README and the MCPB `long_description` will list the requested scopes so the user can copy them when configuring their Zoom Marketplace app.

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
  "manifest_version": "0.2",
  "name": "zoom-team-chat-search",
  "display_name": "Zoom Team Chat & Transcripts",
  "version": "2.0.0",
  "description": "Read-only search across Zoom Team Chat messages and meeting transcripts.",
  "author": {"name": "Alex Craig"},
  "icon": "icon.png",
  "license": "MIT",
  "keywords": ["zoom", "team chat", "transcripts", "search"],
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
  "compatibility": {
    "runtimes": {"python": ">=3.10"}
  }
}
```

### 14.3 Build script

`scripts/build_mcpb.sh` produces 4 platform-specific `.mcpb` files using the official `@anthropic-ai/mcpb` packaging tool:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
mkdir -p "$DIST"

PLATFORMS=("macosx_11_0_arm64" "macosx_11_0_x86_64" \
           "manylinux_2_17_x86_64" "win_amd64")
PLATFORM_TAGS=("darwin-arm64" "darwin-x64" "linux-x64" "win-x64")

for i in "${!PLATFORMS[@]}"; do
  PIP_PLATFORM="${PLATFORMS[$i]}"
  TAG="${PLATFORM_TAGS[$i]}"
  STAGE="$ROOT/build/$TAG"

  rm -rf "$STAGE"
  mkdir -p "$STAGE/server/lib"

  cp -r "$ROOT/server" "$STAGE/"
  cp "$ROOT/manifest.json" "$STAGE/"
  cp "$ROOT/icon.png"      "$STAGE/"

  pip download \
    --platform "$PIP_PLATFORM" \
    --python-version 3.11 \
    --only-binary :all: \
    --no-deps -d "$STAGE/server/lib" \
    -r "$ROOT/requirements.txt"

  # Resolve transitive deps too
  pip download \
    --platform "$PIP_PLATFORM" \
    --python-version 3.11 \
    --only-binary :all: \
    -d "$STAGE/server/lib" \
    -r "$ROOT/requirements.txt"

  # Unpack wheels for runtime import
  for whl in "$STAGE/server/lib"/*.whl; do
    unzip -qo "$whl" -d "$STAGE/server/lib"
    rm "$whl"
  done

  npx --yes @anthropic-ai/mcpb pack "$STAGE" "$DIST/zoom-mcp-${TAG}.mcpb"
  rm -rf "$STAGE"
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
| Unit | File mime-type gate | Assert `zoom_get_file` decodes only allow-listed text MIME types |
| Integration | OAuth flow | Mock Zoom token endpoint via local httpx mock |
| Integration | TLS minimum version | Live call to api.zoom.us, assert TLSv1_2+ |
| Integration | AI Companion search/ask | Mocked AI Companion API; assert source-list mapping, citation parsing |
| Integration | Shared spaces tools | Mocked endpoints; verify list/get with various `include` modes |
| Integration | Reactions + attachments inline | Mock message responses with reactions/files; assert pass-through |
| Integration | Mention groups | Mocked endpoint; assert response shape |
| Smoke (manual) | End-to-end MCPB install on macOS, Linux, Windows | Manual test plan in `docs/release-checklist.md` |

## 17. Migration from v1

- Existing v1 token files (`<repo>/tokens/`) are NOT migrated. v2 forces a fresh OAuth on first install — security-cleaner.
- Users with v1 in `~/.claude.json` should remove that entry manually; a one-shot `scripts/cleanup-v1.sh` is provided for convenience.
- Version bump to `2.0.0` reflects breaking changes in tool surface, distribution, and storage paths.

## 18. Open Questions

None at design time. Items deferred for future work but not blocking this design:
- Local FTS5 message index (Approach B from brainstorming) if live parallel search proves too slow at >500 channels.
- Webhook receiver for real-time updates (would require x-zm-signature verification path).
- macOS Keychain / Windows Credential Vault integration for tokens (replaces Fernet+key-file).
