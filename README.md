# Zoom Team Chat MCP Server

An MCP server that gives Claude Code full access to the Zoom Team Chat API - read messages, send messages, manage channels, search contacts, and more through natural conversation.

## Setup (2 minutes)

### Prerequisites

- Python 3.8+
- A Zoom OAuth app (see below)

### Option A: Let Claude do it

Start Claude Code anywhere and say:

> Clone https://github.com/AlexPortSwigger/zoom-mcp-server and set it up

Claude will read the CLAUDE.md, run the setup script, and walk you through providing your Zoom credentials. Restart Claude Code and you're done.

### Option B: Manual setup

```bash
git clone https://github.com/AlexPortSwigger/zoom-mcp-server.git
cd zoom-mcp-server
chmod +x setup.sh zoom_wrapper.sh
./setup.sh
```

The setup script will:
1. Create a Python virtual environment and install dependencies
2. Prompt you for your Zoom Client ID and Secret
3. Register the server with Claude Code (`~/.claude.json`)

Then restart Claude Code.

### Creating a Zoom OAuth App

If you don't already have one:

1. Go to [marketplace.zoom.us](https://marketplace.zoom.us/) > **Develop** > **Build App** > **General App**
2. Set the redirect URL to: `http://localhost:8000/oauth/callback`
3. Add these scopes:
   - `chat_message:read`, `chat_message:write`
   - `chat_channel:read`, `chat_channel:write`
   - `contact:read`, `user:read`
4. Copy your **Client ID** and **Client Secret**

### First Use

After restarting Claude Code, the first time you use a Zoom tool it will open your browser to authorize with Zoom. This is a one-time step - tokens refresh automatically after that.

## What you can do

Once set up, ask Claude things like:

- "List my Zoom channels"
- "Show me recent messages in the #devs channel"
- "Send a message to the team channel saying 'standup in 5 mins'"
- "Search my messages for anything about Q2 planning"
- "Who's in the engineering channel?"

## Available Tools

| Tool | Description |
|------|-------------|
| `zoom_list_channels` | List channels you belong to |
| `zoom_list_messages` | Read messages from a channel or DM |
| `zoom_send_message` | Send a message to a channel or contact |
| `zoom_search_channels` | Search for channels by name |
| `zoom_list_contacts` | List your Zoom contacts |
| `zoom_list_channel_members` | See who's in a channel |
| `zoom_get_channel` | Get channel details |
| `zoom_get_contact` | Get contact details and presence |
| `zoom_search_company_contacts` | Search contacts by name/email |
| + 18 more | Reactions, bookmarks, pinned messages, shared spaces, etc. |

## File Structure

```
zoom-mcp-server/
├── CLAUDE.md              # Instructions for Claude Code (auto-setup)
├── README.md              # This file
├── setup.sh               # Automated setup script
├── .env.example           # Template for credentials
├── requirements.txt       # Python dependencies
├── zoom_wrapper.sh        # Entry point (loads .env, activates venv)
├── zoom_server.py         # Main server (27 Zoom API endpoints)
├── zoom_oauth_handler.py  # Zoom OAuth implementation
├── base_mcp_server.py     # Base MCP server class
└── utils/                 # OAuth + token management utilities
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Authentication required" | Ask Claude to "authenticate with Zoom" - opens browser |
| Server won't start | Check `logs/zoom-integration.log` and verify `.env` |
| OAuth callback fails | Check port 8000 is free; verify redirect URL in Zoom app |
| SSL errors on macOS | Run `/Applications/Python\ 3.x/Install\ Certificates.command` |
| Missing tools after setup | Restart Claude Code - MCP servers load at startup |

## Security

- Tokens encrypted at rest (Fernet)
- Credentials in `.env` (gitignored)
- File permissions locked to owner only (0o600)
- Each user gets their own tokens via individual OAuth flow
