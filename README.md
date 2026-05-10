# Zoom MCP Server v2

Read-only MCP server for Zoom Team Chat and meeting transcripts. Distributed as a `.mcpb` bundle.

## What's available (22 tools)

| Category | Tools |
|---|---|
| **AI Companion** | `zoom_search`, `zoom_ask` |
| **Auth & info** | `zoom_authenticate`, `zoom_revoke_authentication`, `zoom_get_my_info`, `zoom_resolve` |
| **Channels** | `zoom_list_channels` (incl. starred filter), `zoom_list_channel_members`, `zoom_list_contacts` |
| **Messages** | `zoom_get_channel_history`, `zoom_get_thread`, `zoom_get_message`, `zoom_list_pinned_messages`, `zoom_list_bookmarks`, `zoom_list_mention_groups` |
| **Files** | `zoom_get_file` (text content for text/code MIME types) |
| **Shared spaces** | `zoom_list_shared_spaces`, `zoom_get_shared_space` |
| **Meetings** | `zoom_list_meetings`, `zoom_get_meeting`, `zoom_list_recordings`, `zoom_get_meeting_transcript` |

`zoom_search` and `zoom_ask` use Zoom AI Companion to search and answer questions across Zoom Meetings, Chat, and Docs in a single call with grounded citations — replacing the older "search every channel manually" workflow.

## Install (Claude Desktop)

1. Set up a Zoom Marketplace OAuth app — see [Zoom OAuth setup](#zoom-oauth-setup).
2. Download `zoom-mcp-<your-platform>.mcpb` from the [Releases page](#).
3. Double-click the `.mcpb` file. Claude Desktop prompts for your Zoom Client ID and Secret.
4. Restart Claude Desktop. The Zoom tools appear automatically.

## Install (Claude Code)

```bash
claude mcp install /path/to/zoom-mcp-<your-platform>.mcpb
```

## First use

Ask Claude to "authenticate with Zoom". Your browser will open to authorize the app. Tokens are saved locally and refreshed automatically thereafter.

## Zoom OAuth setup

1. Go to https://marketplace.zoom.us/ → **Develop** → **Build App** → **General App**
2. Set the redirect URL to: `http://localhost:8000/oauth/callback`
3. Add these 28 read-only scopes:

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

4. Copy your **Client ID** and **Client Secret** into the `.mcpb` install prompt.

## Security & data handling

- **TLS 1.2+ enforced** on all Zoom traffic.
- **OAuth tokens are Fernet-encrypted at rest** (AES-128-CBC + HMAC-SHA256) in:
  - macOS: `~/Library/Application Support/zoom-mcp/`
  - Linux: `${XDG_DATA_HOME:-~/.local/share}/zoom-mcp/`
  - Windows: `%APPDATA%\zoom-mcp\`
- **File mode `0600`** on all token and key files (Unix).
- **SQLite metadata cache** stores channel/contact/meeting names and IDs only. **No message bodies, transcript content, or attachment data are ever written to disk.**
- **Logs scrub** bearer tokens, refresh tokens, message bodies, transcript text, and email addresses (defence in depth).
- **`zoom_revoke_authentication`** wipes tokens, cache, and in-memory state at any time.
- **No webhooks** — pure outbound polling/request-response only, so x-zm-signature verification is N/A.

## Development

```bash
git clone https://github.com/AlexPortSwigger/zoom-mcp-server.git
cd zoom-mcp-server
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Run the test suite
.venv/bin/pytest

# Run the server from source (set ZOOM_CLIENT_ID + ZOOM_CLIENT_SECRET in .env)
./scripts/dev-run.sh

# Build .mcpb bundle for the host platform
./scripts/build_mcpb.sh

# Build .mcpb bundles for all four supported platforms (needs internet)
./scripts/build_mcpb.sh --all
```

## License

MIT
