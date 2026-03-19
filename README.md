# Zoom Team Chat MCP Server

An MCP (Model Context Protocol) server that gives Claude Code full access to the Zoom Team Chat API. This lets Claude read messages, send messages, manage channels, search contacts, and more - all through natural conversation.

## What can it do?

- List and search your Zoom channels
- Read and send messages in any channel or DM
- Search messages across conversations
- Manage channel members
- View contacts and their presence status
- React to messages, pin/unpin, bookmark
- Access shared spaces and custom emojis

## Quick Start

### 1. Create a Zoom OAuth App

1. Go to [Zoom App Marketplace](https://marketplace.zoom.us/)
2. Click **Develop** > **Build App**
3. Choose **General App**
4. Fill in the app details (name it whatever you like)
5. Under **OAuth**, set the redirect URL to: `http://localhost:8000/oauth/callback`
6. Add the following **scopes** (under Scopes > Add Scopes):

   **Required scopes:**
   - `chat_message:read` - Read chat messages
   - `chat_message:write` - Send/edit/delete messages
   - `chat_channel:read` - List and view channels
   - `chat_channel:write` - Create/update/delete channels
   - `contact:read` - View contacts
   - `user:read` - View user info

   **Optional (for full functionality):**
   - `chat_channel:read:admin` - Admin channel access
   - `chat_channel:write:admin` - Admin channel management
   - `bookmark:read` - Read bookmarks
   - `bookmark:write` - Manage bookmarks
   - `file:read` - Access chat files

7. Note your **Client ID** and **Client Secret**

### 2. Install Dependencies

```bash
cd zoom-mcp-standalone
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and add your Zoom credentials:

```bash
ZOOM_CLIENT_ID=your_client_id_here
ZOOM_CLIENT_SECRET=your_client_secret_here
```

### 4. Make the wrapper executable

```bash
chmod +x zoom_wrapper.sh
```

### 5. Add to Claude Code

Add the server to your Claude Code MCP configuration. You can do this in one of two ways:

**Option A: Project-level** (`mcp-config.json` in your project root):
```json
{
  "mcpServers": {
    "zoom-integration": {
      "command": "bash",
      "args": ["/full/path/to/zoom-mcp-standalone/zoom_wrapper.sh"]
    }
  }
}
```

**Option B: Global** (`~/.claude/settings.json`):
```json
{
  "mcpServers": {
    "zoom-integration": {
      "command": "bash",
      "args": ["/full/path/to/zoom-mcp-standalone/zoom_wrapper.sh"]
    }
  }
}
```

### 6. Authenticate

Start Claude Code and ask it to authenticate with Zoom:

> "Authenticate with Zoom"

This will open your browser for OAuth authorization. Sign in with your Zoom account and grant access. The tokens are stored locally in the `tokens/` directory (encrypted).

## File Structure

```
zoom-mcp-standalone/
├── README.md                  # This file
├── .env.example               # Template for environment variables
├── .env                       # Your credentials (create from .env.example)
├── requirements.txt           # Python dependencies
├── zoom_wrapper.sh            # Shell wrapper that loads .env and starts server
├── zoom_server.py             # Main server with all Zoom API endpoints
├── zoom_oauth_handler.py      # Zoom-specific OAuth implementation
├── base_mcp_server.py         # Base MCP server class (shared infrastructure)
├── utils/                     # Shared utilities
│   ├── __init__.py
│   ├── oauth_handler.py       # Generic OAuth2 flow handler
│   └── token_manager.py       # Encrypted token storage
├── tokens/                    # OAuth tokens (created automatically, gitignored)
└── logs/                      # Server logs (created automatically)
```

## Usage Examples

Once connected, you can ask Claude things like:

- "List my Zoom channels"
- "Show me recent messages in the #devs channel"
- "Send a message to the Minions channel saying 'standup in 5 mins'"
- "Search my messages for anything about the Q2 planning"
- "Who's in the CoD core channel?"

## Troubleshooting

### "Authentication required" error
Run `zoom_authenticate` - your tokens may have expired and need a browser-based refresh.

### Server won't start
- Check that `.env` exists and has valid credentials
- Verify Python 3.8+ is installed: `python3 --version`
- Check dependencies: `pip install -r requirements.txt`
- Look at logs in `logs/zoom-integration.log`

### OAuth callback fails
- Make sure nothing else is running on port 8000
- Verify your Zoom app's redirect URL matches: `http://localhost:8000/oauth/callback`
- Check that your Zoom app is activated (not in draft mode)

### SSL certificate errors
If you see SSL errors, install Python certificates:
```bash
# macOS
/Applications/Python\ 3.x/Install\ Certificates.command

# Or via pip
pip install certifi
```

## Security Notes

- OAuth tokens are encrypted at rest using Fernet encryption
- Encryption keys and tokens are stored with restrictive file permissions (0o600)
- Never commit your `.env` file or `tokens/` directory to git
- Each user should create their own Zoom OAuth app or authorize against a shared one

## Adding to .gitignore

If you put this in a git repo, add these lines to `.gitignore`:

```
.env
tokens/
logs/
__pycache__/
```
