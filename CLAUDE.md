# Zoom MCP Server - Setup Instructions for Claude Code

This is a self-installing MCP server. When a user asks you to set it up, follow these steps exactly.

## Automated Setup

Run the setup script. It handles everything: venv, dependencies, .env, and Claude Code MCP registration.

```bash
chmod +x setup.sh zoom_wrapper.sh
./setup.sh
```

The script will prompt the user for their Zoom Client ID and Client Secret if not already configured. If the user doesn't have a Zoom app yet, guide them:

1. Go to https://marketplace.zoom.us/ > Develop > Build App > General App
2. Set redirect URL to: `http://localhost:8000/oauth/callback`
3. Add these scopes: `chat_message:read`, `chat_message:write`, `chat_channel:read`, `chat_channel:write`, `contact:read`, `user:read`
4. Copy the Client ID and Client Secret

If the user already has the credentials, you can pass them directly:

```bash
./setup.sh --client-id "THEIR_ID" --client-secret "THEIR_SECRET"
```

## After Setup

Tell the user to restart Claude Code. On the next session, the Zoom tools will be available automatically.

The first time a Zoom tool is used, it will trigger an OAuth flow that opens the user's browser to authorize with Zoom. After that, tokens are stored locally and refresh automatically.

## What This Server Provides

Once configured, these Zoom Team Chat tools become available:
- `zoom_list_channels` - List all channels
- `zoom_list_messages` - Read messages from channels/DMs
- `zoom_send_message` - Send messages
- `zoom_search_channels` - Search channels
- `zoom_list_contacts` - View contacts
- `zoom_list_channel_members` - See who's in a channel
- Plus 20+ more endpoints

## Troubleshooting

If the server fails to start after setup:
1. Check logs: `cat logs/zoom-integration.log`
2. Verify .env has credentials: `cat .env`
3. Test the venv: `.venv/bin/python3 -c "import mcp; print('OK')"`
4. Re-run setup: `./setup.sh`
