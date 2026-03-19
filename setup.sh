#!/bin/bash
#
# Zoom MCP Server - Automated Setup
# Run this script to install dependencies, configure credentials,
# and register the server with Claude Code.
#
# Usage: ./setup.sh [--client-id ID] [--client-secret SECRET]
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# --- Parse arguments ---
ZOOM_CLIENT_ID_ARG=""
ZOOM_CLIENT_SECRET_ARG=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --client-id) ZOOM_CLIENT_ID_ARG="$2"; shift 2 ;;
        --client-secret) ZOOM_CLIENT_SECRET_ARG="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

echo "=== Zoom MCP Server Setup ==="
echo ""

# --- Step 1: Python virtual environment ---
echo "[1/4] Setting up Python virtual environment..."
if [[ ! -d ".venv" ]]; then
    python3 -m venv .venv
    echo "  Created .venv"
else
    echo "  .venv already exists"
fi
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "  Dependencies installed"

# --- Step 2: Configure credentials ---
echo ""
echo "[2/4] Configuring Zoom credentials..."

if [[ -f ".env" ]]; then
    source .env
fi

# Use args if provided, fall back to existing .env, then prompt
CLIENT_ID="${ZOOM_CLIENT_ID_ARG:-$ZOOM_CLIENT_ID}"
CLIENT_SECRET="${ZOOM_CLIENT_SECRET_ARG:-$ZOOM_CLIENT_SECRET}"

if [[ -z "$CLIENT_ID" || "$CLIENT_ID" == "your_client_id_here" ]]; then
    echo ""
    echo "  You need a Zoom OAuth app. If you don't have one:"
    echo "  1. Go to https://marketplace.zoom.us/"
    echo "  2. Click Develop > Build App > General App"
    echo "  3. Set redirect URL to: http://localhost:8000/oauth/callback"
    echo "  4. Add scopes: chat_message:read, chat_message:write,"
    echo "     chat_channel:read, chat_channel:write, contact:read, user:read"
    echo ""
    read -p "  Enter your Zoom Client ID: " CLIENT_ID
fi

if [[ -z "$CLIENT_SECRET" || "$CLIENT_SECRET" == "your_client_secret_here" ]]; then
    read -p "  Enter your Zoom Client Secret: " CLIENT_SECRET
fi

if [[ -z "$CLIENT_ID" || -z "$CLIENT_SECRET" ]]; then
    echo "  ERROR: Client ID and Secret are required."
    exit 1
fi

cat > .env << ENVEOF
ZOOM_CLIENT_ID=${CLIENT_ID}
ZOOM_CLIENT_SECRET=${CLIENT_SECRET}
ZOOM_REDIRECT_URI=http://localhost:8000/oauth/callback
ENVEOF

echo "  Credentials saved to .env"

# --- Step 3: Register with Claude Code ---
echo ""
echo "[3/4] Registering MCP server with Claude Code..."

CLAUDE_CONFIG="$HOME/.claude.json"
WRAPPER_PATH="$SCRIPT_DIR/zoom_wrapper.sh"

# Create ~/.claude.json if it doesn't exist
if [[ ! -f "$CLAUDE_CONFIG" ]]; then
    echo '{"mcpServers":{}}' > "$CLAUDE_CONFIG"
    echo "  Created $CLAUDE_CONFIG"
fi

# Use python to safely merge into the JSON config
python3 -c "
import json, sys

config_path = '$CLAUDE_CONFIG'
wrapper_path = '$WRAPPER_PATH'

try:
    with open(config_path, 'r') as f:
        config = json.load(f)
except (json.JSONDecodeError, FileNotFoundError):
    config = {}

if 'mcpServers' not in config:
    config['mcpServers'] = {}

config['mcpServers']['zoom-integration'] = {
    'type': 'stdio',
    'command': 'bash',
    'args': [wrapper_path]
}

with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)

print('  Registered zoom-integration in ' + config_path)
"

# --- Step 4: Update wrapper to use venv ---
echo ""
echo "[4/4] Finalising..."

# Verify the setup
echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Restart Claude Code (quit and reopen)"
echo "  2. Ask Claude: 'Authenticate with Zoom'"
echo "     (this will open your browser to authorize the app)"
echo "  3. Once authenticated, you can use Zoom tools like:"
echo "     - 'List my Zoom channels'"
echo "     - 'Show messages in the #general channel'"
echo "     - 'Send a message to the team channel'"
echo ""
