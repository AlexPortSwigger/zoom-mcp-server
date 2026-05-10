# Zoom MCP Server v2.1

Read-only MCP server for Zoom Team Chat and meeting transcripts. **Zero-config beta** — no client secret to enter, no setup script. Distributed as a `.mcpb` bundle.

## Install for Swiggers (zero config)

1. Download `zoom-mcp-<your-platform>.mcpb` from internal share
2. Double-click to install in Claude Desktop (no prompts, nothing to enter)
3. In Claude: **"authenticate with Zoom"**
4. Browser opens → log in to Zoom (you probably already are) → click **Allow**
5. Browser shows "Authorization successful" and auto-closes
6. Done — Claude can now read your Zoom Team Chat and meeting transcripts

That's it. No credentials. The MCPB has the PortSwigger Zoom dev app's **public client ID** baked in, and uses **PKCE** (RFC 7636) so no client secret is needed anywhere.

## What's available (22 tools)

| Category | Tools |
|---|---|
| **Auth** | `zoom_authenticate`, `zoom_revoke_authentication` |
| **AI Companion** | `zoom_search`, `zoom_ask` |
| **Info & resolve** | `zoom_get_my_info`, `zoom_resolve` |
| **Channels** | `zoom_list_channels` (incl. starred filter), `zoom_list_channel_members`, `zoom_list_contacts` |
| **Messages** | `zoom_get_channel_history`, `zoom_get_thread`, `zoom_get_message`, `zoom_list_pinned_messages`, `zoom_list_bookmarks`, `zoom_list_mention_groups` |
| **Files** | `zoom_get_file` (text content for text/code MIME types) |
| **Shared spaces** | `zoom_list_shared_spaces`, `zoom_get_shared_space` |
| **Meetings** | `zoom_list_meetings`, `zoom_get_meeting`, `zoom_list_recordings`, `zoom_get_meeting_transcript` |

`zoom_search` and `zoom_ask` use Zoom AI Companion to search and answer questions across Zoom Meetings, Chat, and Docs in a single call with grounded citations.

## How the auth flow works

```
┌────────────┐     ┌──────────────┐     ┌──────────────────────────┐
│  Claude    │────►│   Browser    │────►│   zoom.us/oauth/         │
│ (zoom_     │     │  (you log    │     │      authorize           │
│  authent-  │     │  in & click  │     │  ?code_challenge=…       │
│  icate)    │     │   Allow)     │     │                           │
└────────────┘     └──────┬───────┘     └────────────┬─────────────┘
                          │                            │
                          │  redirect with ?code=…     │
                          ▼                            │
                  ┌────────────────────────────────────▼─────────────┐
                  │  http://localhost:8000/oauth/callback             │
                  │  (MCPB's local listener auto-captures the code)   │
                  └─────────────────────┬────────────────────────────┘
                                         │
                                         ▼ exchange code + verifier
                              ┌─────────────────────┐
                              │  zoom.us/oauth/     │
                              │  token              │
                              │  (NO client_secret) │
                              └──────────┬──────────┘
                                         │ access + refresh tokens
                                         ▼
                              Encrypted at rest in:
                              macOS:   ~/Library/Application Support/zoom-mcp/
                              Linux:   ${XDG_DATA_HOME:-~/.local/share}/zoom-mcp/
                              Windows: %APPDATA%\zoom-mcp\
```

The PKCE `code_verifier` never leaves your machine. The `code_challenge` (SHA-256 hash of the verifier) is the only thing the auth server sees.

## One-time PortSwigger admin setup (already done)

Documented for the record:

1. **Zoom Marketplace dev app** — toggle on **"Use Public Client OAuth"** (PKCE; removes the need for a client secret)
2. **OAuth Redirect URL** → `http://localhost:8000/oauth/callback`
   - Dev apps allow http://localhost (production apps require HTTPS)
3. **OAuth scopes** (28 read-only — see [list below](#oauth-scopes))
4. **App is User-managed** so individual Swiggers can authorise it themselves

When promoting from dev → production, the redirect URI will need to move to an HTTPS endpoint (e.g. a small static page on a portswigger.net path or GitHub Pages). The MCPB code already supports that path via the `ZOOM_REDIRECT_URI` env var.

## Security & data handling

- **TLS 1.2+ enforced** on all Zoom traffic
- **PKCE** — no `client_secret` ever distributed or stored
- **State verification** on the OAuth callback to prevent CSRF
- **OAuth tokens Fernet-encrypted at rest** (mode 0600) in your OS-standard user-data dir
- **SQLite metadata cache** stores channel/contact/meeting names and IDs only — **no message bodies, transcript content, or attachment data are ever written to disk**
- **Logs scrub** bearer tokens, refresh tokens, message bodies, transcript text, search queries, and email addresses
- **`zoom_revoke_authentication`** wipes tokens, cache, and in-memory state at any time
- **No webhooks** — pure outbound polling/request-response only

## OAuth scopes

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

## Forking / using a different Zoom app

To use this with a different org's Zoom app:

1. Create a Zoom Marketplace app, enable **Use Public Client OAuth**, copy the **Public Client ID**
2. Set OAuth redirect to `http://localhost:8000/oauth/callback` (dev app) or your HTTPS callback (production)
3. Edit `server/main.py` → change `DEFAULT_CLIENT_ID` and `DEFAULT_REDIRECT_URI`
4. Or set `ZOOM_CLIENT_ID` and `ZOOM_REDIRECT_URI` in `manifest.json` → `mcp_config.env`
5. Rebuild: `./scripts/build_mcpb.sh --all`

## Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| "Port 8000 already in use" | Another process listening on 8000 | `lsof -i :8000` to find it; kill or wait, then re-run `zoom_authenticate` |
| Auth window closed without authorising | Just close-and-retry | Re-run `zoom_authenticate` |
| 5-minute auth timeout | Tab was lost / forgotten | Re-run `zoom_authenticate` |
| Tokens expired and refresh fails | Refresh token revoked or 30-day window passed | Run `zoom_revoke_authentication`, then `zoom_authenticate` |

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
