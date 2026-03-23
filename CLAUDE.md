# Zoom MCP Server - Setup Instructions for Claude Code

This is a self-installing MCP server. When a user asks you to set it up, follow these steps exactly.

## Automated Setup (Claude Code CLI)

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

## Claude Desktop App Setup

The Claude Desktop app uses a different config file and cannot execute bash wrapper scripts (especially from cloud-synced drives like Google Drive due to macOS Gatekeeper). Follow these steps instead:

### Step 1: Copy files to a local path

Copy the server files to a local directory outside of any cloud-synced folder:

```bash
LOCAL_DIR="$HOME/.zoom-mcp"
mkdir -p "$LOCAL_DIR"
cp zoom_server.py zoom_oauth_handler.py base_mcp_server.py requirements.txt "$LOCAL_DIR/"
cp -r utils "$LOCAL_DIR/"
```

### Step 2: Create venv and install dependencies

```bash
cd "$LOCAL_DIR"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Step 3: Create .env file

```bash
cat > "$LOCAL_DIR/.env" << 'EOF'
ZOOM_CLIENT_ID=<user's client id>
ZOOM_CLIENT_SECRET=<user's client secret>
ZOOM_REDIRECT_URI=http://localhost:8000/oauth/callback
EOF
```

### Step 4: Add to Claude Desktop config

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` and add the `zoom-integration` entry to the `mcpServers` object. **Important**: Use the Python binary directly (not a bash wrapper) and pass env vars inline:

```json
{
  "mcpServers": {
    "zoom-integration": {
      "command": "<HOME_DIR>/.zoom-mcp/.venv/bin/python3",
      "args": [
        "<HOME_DIR>/.zoom-mcp/zoom_server.py"
      ],
      "env": {
        "ZOOM_CLIENT_ID": "<user's client id>",
        "ZOOM_CLIENT_SECRET": "<user's client secret>",
        "ZOOM_REDIRECT_URI": "http://localhost:8000/oauth/callback"
      }
    }
  }
}
```

Replace `<HOME_DIR>` with the user's actual home directory path (e.g. `/Users/username`).

### Step 5: Restart Claude Desktop

Quit and reopen the Claude Desktop app. The Zoom tools will appear automatically.

### Why not use the bash wrapper?

macOS Gatekeeper blocks execution of shell scripts from cloud-synced directories (Google Drive, iCloud, Dropbox, etc.) with `Operation not permitted`. Even if the repo is cloned locally, Claude Desktop doesn't reliably pass env vars through bash wrappers. Calling the venv Python binary directly with inline env vars is the most reliable approach.

## After Setup

Tell the user to restart Claude Code / Claude Desktop. On the next session, the Zoom tools will be available automatically.

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

### Claude Desktop specific issues

| Problem | Solution |
|---------|----------|
| `Operation not permitted` | Server files are on a cloud-synced drive. Copy to a local path like `~/.zoom-mcp/` |
| Config not picked up | Ensure you edited `~/Library/Application Support/Claude/claude_desktop_config.json` (not `~/.claude.json` which is for Claude Code CLI) |
| Still using old config | Fully quit Claude Desktop (Cmd+Q) and reopen — just closing the window isn't enough |
| Python not found | Use the full absolute path to the venv Python binary |
