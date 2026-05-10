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

## What's available (20 tools)

| Category | Tools |
|---|---|
| **Auth** | `zoom_authenticate`, `zoom_revoke_authentication` |
| **Info & resolve** | `zoom_get_my_info`, `zoom_resolve` |
| **Cross-channel search** | `zoom_search_messages` (parallel fan-out across channels + DMs) |
| **Channels** | `zoom_list_channels` (with `starred` filter), `zoom_list_channel_members`, `zoom_list_contacts` |
| **Messages** | `zoom_get_channel_history`, `zoom_get_thread`, `zoom_get_message`, `zoom_list_pinned_messages` *(unverified)* |
| **Shared spaces** | `zoom_list_shared_spaces`, `zoom_get_shared_space` *(unverified)* |
| **Meetings** | `zoom_list_meetings`, `zoom_get_meeting`, `zoom_list_recordings`, `zoom_get_meeting_transcript` |
| **AI Companion meeting summaries** | `zoom_list_meeting_summaries`, `zoom_get_meeting_summary` |

Attachments and emoji reactions appear inline on every message returned by the message tools (when the corresponding scopes are granted).

### What's *not* in v2.2

We removed three things from the v2.0/v2.1 design after verifying they don't have public Zoom APIs:

- ~~`zoom_search`, `zoom_ask`~~ — Zoom doesn't expose AI Companion `search`/`ask` over a public API. Replaced by `zoom_search_messages` (manual fan-out, no AI ranking) and `zoom_list_meeting_summaries` / `zoom_get_meeting_summary` (the *real* AI Companion APIs).
- ~~`zoom_list_bookmarks`~~ — bookmarks appear to be UI-only.
- ~~`zoom_list_mention_groups`~~ — confirmed by Zoom forum: no public API for reading mention groups.
- ~~`zoom_get_file`~~ — Zoom has no standalone GET-by-file-id endpoint. Attachment metadata is already returned inline on each message via the `files` array.

The `zoom_list_pinned_messages`, `zoom_list_shared_spaces`, and `zoom_get_shared_space` tools use endpoint paths that aren't fully canonicalised in Zoom's docs. They may return 404; smoke-test them and we'll drop or fix as needed.

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

PKCE `code_verifier` never leaves the machine. State value verified for CSRF protection.

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
contact:read:list_contacts
meeting:read:meeting
meeting_summary:read:summary
cloud_recording:read:list_user_recordings
cloud_recording:read:list_recording_files
cloud_recording:read:recording
cloud_recording:read:meeting_transcript
cloud_recording:read:content
chat_channel:read
chat_message:read
chat_contact:read
team_chat:read:channel
team_chat:read:user_channel
team_chat:read:list_user_channels
team_chat:read:list_members
team_chat:read:list_user_messages
team_chat:read:user_message
team_chat:read:thread_message
team_chat:read:message_emoji
team_chat:read:list_pinned_messages
team_chat:read:list_contacts
team_chat:read:contact
team_chat:read:shared_space
team_chat:read:list_shared_spaces
team_chat:read:list_shared_space_channels
team_chat:read:list_shared_space_members
user:read:user
```

The deprecated `ai_companion:read:ask` and `ai_companion:read:search` scopes are no longer requested. `meeting_summary:read:summary` is added for the real summary API.

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
| Pinned/shared-spaces tools return errors | Endpoint paths unverified in v2.2 — open an issue with the error |
| Cross-channel search is slow | Concurrency is capped at 20; expect 1-3s for ≤200 channels, ~5-7s for ≤500 |

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
