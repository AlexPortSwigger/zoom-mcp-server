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

| Category | Tools |
|---|---|
| **Auth** | `zoom_authenticate`, `zoom_revoke_authentication` |
| **Info & resolve** | `zoom_get_my_info`, `zoom_resolve` |
| **AI Companion** | `zoom_search` (cross-source search), `zoom_ask` (grounded Q&A with citations) |
| **Manual cross-channel search** | `zoom_search_messages` (parallel fan-out fallback / exact-substring queries) |
| **Channels** | `zoom_list_channels` (with starred filter), `zoom_list_channel_members`, `zoom_list_contacts` |
| **Messages** | `zoom_get_channel_history`, `zoom_get_thread`, `zoom_get_message`, `zoom_list_pinned_messages`, `zoom_list_bookmarks`, `zoom_list_mention_groups` |
| **Files** | `zoom_get_file` (text content for text/code MIME types) |
| **Shared spaces** | `zoom_list_shared_spaces`, `zoom_get_shared_space` |
| **Meetings** | `zoom_list_meetings`, `zoom_get_meeting`, `zoom_list_recordings`, `zoom_get_meeting_transcript` |
| **AI meeting summaries** | `zoom_list_meeting_summaries`, `zoom_get_meeting_summary` |

`zoom_search` and `zoom_ask` use Zoom AI Companion to search and answer questions across Zoom Meetings, Chat, and Docs in a single call with grounded citations. `zoom_search_messages` is the manual fan-out fallback for queries where you want raw substring matching across channels and DMs.

Attachments and emoji reactions appear inline on every message returned by the message tools.

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
