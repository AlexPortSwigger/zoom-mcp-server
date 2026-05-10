# Zoom MCP Server v2.2

Read-only MCP server for Zoom Team Chat and meeting transcripts. **Zero-config** — no client secret to enter, no setup script. Distributed as a `.mcpb` bundle.

## What this connector lets Claude do

| Use case | Tool route |
|---|---|
| "What's been said in #channel today?" | `zoom_message_history(channel, from_date, to_date)` |
| "Summarise #channel this week" | `zoom_message_history` over the date range, then Claude summarises |
| "What did <person> say in #channel?" | `zoom_message_history` for the channel, filter by `sender` in the result |
| "Catch me up on my DMs with <person>" | `zoom_message_history(contact=<email>)` |
| "Find anything about <topic> across chat" | `zoom_search_messages(query, channel_filter?)` |
| "What channels am I in?" | `zoom_chat_channels` (use `starred_only=true` for the active ones) |
| "Who's in #channel?" | `zoom_chat_channel_members` |
| "What meetings do I have today?" | `zoom_meeting_list(type=upcoming)` |
| "Summary of meeting X" | `zoom_meeting_summary_get(meeting_id)` |
| "Recent meeting summaries" | `zoom_meeting_list` then `zoom_meeting_summary_get` per meeting |
| "Transcript of meeting X" | `zoom_meeting_transcript(meeting_id)` |

The MCPB launches an OAuth browser flow on first install (PKCE, no client secret needed). Tokens are Fernet-encrypted on disk; transcripts and chat bodies are never persisted; the SQLite metadata cache stores names and IDs only.

## Endpoint status (verified live 2026-05-10 via `scripts/live_audit.py`)

15 PASS / 1 FAIL / 6 SKIP (skips are tools we can't exercise without specific test data, e.g. a recorded meeting transcript or a chat file ID):

| Tool | Status | Live evidence |
|---|---|---|
| `zoom_auth_whoami` | ✅ | Returned profile |
| `zoom_chat_channels` | ✅ | 1,548 channels |
| `zoom_chat_channel_members` | ✅ | 78 members in #Devs |
| `zoom_chat_contacts` | ✅ | 209 contacts |
| `zoom_chat_shared_spaces` | ✅ | 0 spaces (legitimate empty) |
| `zoom_message_history` | ✅ | 5 messages from #Devs today |
| `zoom_message_get` / `zoom_message_thread` / `zoom_message_pinned` | ✅ | Returned real data |
| `zoom_message_bookmarks` | ✅ | 1 bookmark |
| `zoom_search_messages` | ✅ | 6 hits for "the" |
| `zoom_meeting_list` | ✅ | 10 previous meetings |
| `zoom_meeting_recordings` | ✅ | 0 recordings (legitimate empty for this user) |
| `zoom_meeting_get` | ✅ | Returned meeting topic + manifest |
| `zoom_meeting_summary_get` | ✅ | Endpoint reachable (404 for meetings without AI summaries is correct behaviour) |
| `zoom_chat_shared_space_get`, `zoom_message_file`, `zoom_meeting_transcript`, `zoom_auth_login`/`logout`/`resolve` | ⏭ skip | Need specific test data we don't have (a recorded meeting transcript, a chat file ID, a shared space) or are interactive/destructive |

When a tool fails with a missing-scope error you'll see a single-line message like `HTTP 400 (Zoom code 4711): Zoom OAuth app missing scope. Required: [meeting:read:list_summaries:admin]. Fix: a Zoom Marketplace admin must add the missing scope(s)…` — the message names exactly what to add and where.

### Why no `zoom_meeting_summary_list`

The corresponding Zoom REST endpoint (`GET /meetings/meeting_summaries`) demands `meeting:read:list_summaries:admin`, a `:admin` scope [exposed only to Server-to-Server OAuth apps](https://devforum.zoom.us/t/cannot-retrieve-ai-companion-meeting-summary-body-via-api-missing-meetingsummary-master-scope/142967), not the User-managed PKCE app this connector ships. Rather than expose a tool that always 4711s, v2.2.6 drops it.

Workaround that's just as good for the "show me recent summaries" workflow: Claude calls `zoom_meeting_list` → picks meetings → calls `zoom_meeting_summary_get` per meeting. `zoom_meeting_summary_get` works fine on the non-`:admin` `meeting:read:summary` scope.

When a tool fails with a missing-scope error you'll see a single-line message like `HTTP 400 (Zoom code 4711): Zoom OAuth app missing scope. Required: [meeting:read:list_meetings]. Fix: a Zoom Marketplace admin must add the missing scope(s)…` — the message names exactly what to add and where.

### Tools removed in v2.2.5

These three tools' Zoom REST URLs do not exist publicly — verified against Zoom's published [AI Companion OpenAPI spec](https://developers.zoom.us/docs/api/ai-companion/) (one endpoint, archive only) and exhaustive URL probing:

- `zoom_search_ai`, `zoom_search_ask` — the `ai_companion:read:search`/`:ask` scopes are advertised by Zoom but no REST URL accepts them. The only AI Companion REST endpoint that exists is `GET /v2/aic/users/{userId}/conversation_archive` (admin-only compliance archive download).
- `zoom_message_mentions` — `/chat/channels/{id}/mention_groups` returns code 2300 ("endpoint not recognized") for every URL variant tested.

If Zoom ships these endpoints in future, re-adding the tools is a one-line change in `server/endpoints.py`.

## Install (zero config)

1. Download `zoom-mcp-<your-platform>.mcpb`
2. Double-click to install in Claude Desktop (no prompts, nothing to enter)
3. The connector launches the browser OAuth flow on first run — log in to Zoom, click **Allow**
4. Browser auto-closes; Claude tells you you're authenticated
5. Done

The MCPB has the PortSwigger Zoom dev app's **public client ID** baked in, and uses **PKCE** (RFC 7636) — no client secret anywhere, and no environment variables required.

## What's available (21 tools)

Each tool has standard MCP annotations, so Claude Desktop's connector-permissions screen groups them into:

- **Read-only (19 tools)** — every Zoom API call we expose
- **Write (1 tool)** — `zoom_auth_login` (saves OAuth tokens locally)
- **Destructive (1 tool)** — `zoom_auth_logout` (wipes local tokens, cache, in-memory state)

Tool names share group prefixes (`zoom_auth_*`, `zoom_chat_*`, `zoom_meeting_*`, `zoom_message_*`, `zoom_search_*`):

**`zoom_auth_*`** — `zoom_auth_login`, `zoom_auth_logout`, `zoom_auth_resolve`, `zoom_auth_whoami`

**`zoom_chat_*`** — `zoom_chat_channels` (with `starred_only`), `zoom_chat_channel_members`, `zoom_chat_contacts`, `zoom_chat_shared_spaces`, `zoom_chat_shared_space_get`

**`zoom_meeting_*`** — `zoom_meeting_list`, `zoom_meeting_get`, `zoom_meeting_recordings`, `zoom_meeting_transcript`, `zoom_meeting_summary_get`

**`zoom_message_*`** — `zoom_message_history` (auto-paginated channel/DM history with reactions + attachment metadata inline), `zoom_message_thread`, `zoom_message_get`, `zoom_message_file`, `zoom_message_pinned`, `zoom_message_bookmarks`

**`zoom_search_*`** — `zoom_search_messages` (parallel fan-out keyword search across chat)

## How auth works

```
Claude → Browser → zoom.us/oauth/authorize?code_challenge=… → user clicks Allow
                                                     ↓
                             http://localhost:8000/oauth/callback ←  MCPB local listener
                                                     ↓
                             zoom.us/oauth/token  (code + verifier; NO secret)
                                                     ↓
                             Tokens encrypted at rest in:
                               macOS:   ~/Library/Application Support/zoom-mcp/
                               Linux:   ${XDG_DATA_HOME:-~/.local/share}/zoom-mcp/
                               Windows: %APPDATA%\zoom-mcp\
```

PKCE `code_verifier` never leaves the machine. State value verified on the OAuth callback for CSRF protection.

The browser flow is launched automatically on connector startup if there's no valid session yet (`maybe_auth_on_startup` in `server/main.py`). On subsequent launches with a refresh token, auth is silent.

## OAuth scopes the dev app must have configured

Required (after the connector v2.2.6 changes):

```
# Profile / contacts
user:read:user
contact:read:list_contacts

# Team Chat (read-only)
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
team_chat:read:list_contacts
team_chat:read:contact
team_chat:read:shared_space
team_chat:read:list_shared_spaces
team_chat:read:list_shared_space_channels
team_chat:read:list_shared_space_members

# Meetings + recordings
meeting:read:meeting
meeting:read:list_meetings        ← needed for zoom_meeting_list
meeting:read:summary              ← needed for zoom_meeting_summary_get
cloud_recording:read:list_user_recordings
cloud_recording:read:list_recording_files
cloud_recording:read:recording
cloud_recording:read:meeting_transcript
cloud_recording:read:content
```

After adding scopes in [marketplace.zoom.us](https://marketplace.zoom.us/develop/apps), users must `zoom_auth_logout` then `zoom_auth_login` to get a refreshed token with the new scopes.

> **Scope name pitfalls** (verified live):
> - There is no `meeting:read:list_meetings:admin`, no `meeting:read:list_summaries:admin`, no `meeting:read:summary:admin` in the Zoom Marketplace catalogue — Zoom's 4711 error message *suggests* `:admin` variants but only the non-admin names actually exist for end-user OAuth apps.
> - `meeting_summary:read:summary` (note the underscore) appeared in the older README but is **not** what Zoom checks — the right name is `meeting:read:summary`.

## Security & data handling

- **TLS 1.2+ enforced** on all Zoom traffic
- **PKCE** — no `client_secret` ever distributed or stored
- **OAuth tokens Fernet-encrypted at rest** (mode 0600)
- **SQLite metadata cache** stores channel/contact/meeting names and IDs only — **no message bodies or transcript content on disk**
- **Logs scrub** bearer tokens, refresh tokens, message bodies, transcript text, search queries, and email addresses
- **`zoom_auth_logout`** wipes everything

## Forking

To use this with a different Zoom app:

1. Create a Zoom Marketplace app, enable **Use Public Client OAuth**, copy the **Public Client ID**
2. Set OAuth redirect to `http://localhost:8000/oauth/callback` (dev app) or your HTTPS callback (production)
3. Edit `server/main.py` → change `DEFAULT_CLIENT_ID` and `DEFAULT_REDIRECT_URI`, OR pass them via `mcp_config.env` in `manifest.json`
4. Rebuild: `./scripts/build_mcpb.sh --all`

## Troubleshooting

| Problem | Fix |
|---|---|
| "Port 8000 already in use" | `lsof -i :8000`; kill the conflicting process; re-run `zoom_auth_login` |
| Auth window closed without authorising | Re-run `zoom_auth_login` |
| Tokens expired and refresh fails | `zoom_auth_logout`, then `zoom_auth_login` |
| `HTTP 400 (Zoom code 4711)` on a tool | Zoom OAuth app missing a scope. The error message names exactly which one. Add it in [marketplace.zoom.us](https://marketplace.zoom.us/develop/apps), then `zoom_auth_logout` + `zoom_auth_login`. |
| `zoom_search_messages` returns 0 hits when you expect matches | Zoom caps search windows to ~24h server-side. For older content, use `zoom_message_history` with a date range instead. |

## Development

```bash
git clone https://github.com/AlexPortSwigger/zoom-mcp-server.git
cd zoom-mcp-server
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

.venv/bin/pytest                       # 109 tests
./scripts/dev-run.sh                   # run from source
./scripts/build_mcpb.sh                # build .mcpb for host platform
./scripts/build_mcpb.sh --all          # build .mcpb for all 4 platforms
python3 scripts/diag_endpoints.py      # live-probe endpoints (uses local tokens)
```

## License

MIT
