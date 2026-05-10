# Zoom MCP Server v2.2

Read-only MCP server for Zoom Team Chat and meeting transcripts. **Zero-config beta** — no client secret to enter, no setup script. Distributed as a `.mcpb` bundle.

## Install for Swiggers (zero config)

1. Download `zoom-mcp-<your-platform>.mcpb` from internal share
2. Double-click to install in Claude Desktop (no prompts, nothing to enter)
3. In Claude: **"authenticate with Zoom"**
4. Browser opens → log in to Zoom → click **Allow**
5. Browser auto-closes; Claude tells you you're authenticated
6. Done

The MCPB has the PortSwigger Zoom dev app's **public client ID** baked in, and uses **PKCE** (RFC 7636) — no client secret anywhere.

## What's available (25 tools)

Each tool has standard MCP annotations, so Claude Desktop's connector-permissions screen groups them into:

- **Read-only (23 tools)** — every Zoom API call we expose
- **Write (1 tool)** — `zoom_auth_login` (saves OAuth tokens locally)
- **Destructive (1 tool)** — `zoom_auth_logout` (wipes local tokens, cache, in-memory state)

Within those buckets, tool names share group prefixes (`zoom_auth_*`, `zoom_chat_*`, `zoom_meeting_*`, `zoom_message_*`, `zoom_search_*`) so they alphabetise into tidy sub-sections in any client that sorts by name:

**`zoom_auth_*` — authentication & profile**
- `zoom_auth_login` — start the OAuth flow
- `zoom_auth_logout` — wipe local session
- `zoom_auth_resolve` — name/email → ID
- `zoom_auth_whoami` — authenticated user's profile

**`zoom_chat_*` — channels, contacts, shared spaces**
- `zoom_chat_channels` (with `starred_only` filter)
- `zoom_chat_channel_members`
- `zoom_chat_contacts`
- `zoom_chat_shared_spaces`
- `zoom_chat_shared_space_get`

**`zoom_meeting_*` — meetings, recordings, transcripts, AI summaries**
- `zoom_meeting_list`, `zoom_meeting_get`
- `zoom_meeting_recordings`, `zoom_meeting_transcript`
- `zoom_meeting_summary_list`, `zoom_meeting_summary_get`

**`zoom_message_*` — messages, threads, files, pinned, bookmarks, mentions**
- `zoom_message_history` — auto-paginated channel/DM history with reactions + attachment metadata inline
- `zoom_message_thread`, `zoom_message_get`, `zoom_message_file`
- `zoom_message_pinned`, `zoom_message_bookmarks`, `zoom_message_mentions`

**`zoom_search_*` — AI Companion + manual fan-out**
- `zoom_search_ai` — AI Companion cross-source search
- `zoom_search_ask` — AI Companion grounded Q&A with citations
- `zoom_search_messages` — manual parallel fan-out (substring fallback)

Attachments and emoji reactions appear inline on every message returned by the `zoom_message_*` tools.

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

## One-time PortSwigger admin setup (already done)

1. Zoom Marketplace **dev app** with **Use Public Client OAuth** enabled
2. OAuth redirect URL: `http://localhost:8000/oauth/callback`
3. App is **User-managed** so individual Swiggers authorise it themselves
4. Scopes: see [list below](#oauth-scopes)

## Security & data handling

- **TLS 1.2+ enforced** on all Zoom traffic
- **PKCE** — no `client_secret` ever distributed or stored
- **OAuth tokens Fernet-encrypted at rest** (mode 0600)
- **SQLite metadata cache** stores channel/contact/meeting names and IDs only — **no message bodies or transcript content on disk**
- **Logs scrub** bearer tokens, refresh tokens, message bodies, transcript text, search queries, and email addresses
- **`zoom_revoke_authentication`** wipes everything

## OAuth scopes

```
ai_companion:read:ask
ai_companion:read:search
contact:read:list_contacts
meeting:read:meeting
meeting_summary:read:summary
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

## Forking

To use this with a different Zoom app:

1. Create a Zoom Marketplace app, enable **Use Public Client OAuth**, copy the **Public Client ID**
2. Set OAuth redirect to `http://localhost:8000/oauth/callback` (dev app) or your HTTPS callback (production)
3. Edit `server/main.py` → change `DEFAULT_CLIENT_ID` and `DEFAULT_REDIRECT_URI`, OR pass them via `mcp_config.env` in `manifest.json`
4. Rebuild: `./scripts/build_mcpb.sh --all`

## Troubleshooting

| Problem | Fix |
|---|---|
| "Port 8000 already in use" | `lsof -i :8000`; kill the conflicting process; re-run `zoom_authenticate` |
| Auth window closed without authorising | Re-run `zoom_authenticate` |
| Tokens expired and refresh fails | Run `zoom_revoke_authentication`, then `zoom_authenticate` |
| AI Companion tools 403 | AI Companion not enabled on your account; ask your Zoom admin |

## Development

```bash
git clone https://github.com/AlexPortSwigger/zoom-mcp-server.git
cd zoom-mcp-server
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

.venv/bin/pytest                 # run test suite
./scripts/dev-run.sh             # run from source
./scripts/build_mcpb.sh          # build .mcpb for host platform
./scripts/build_mcpb.sh --all    # build .mcpb for all 4 platforms
```

## License

MIT
