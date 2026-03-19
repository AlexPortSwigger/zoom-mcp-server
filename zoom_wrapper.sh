#!/bin/bash

# Zoom MCP Server Wrapper
# Loads environment variables, activates venv, and starts the server

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
VENV_DIR="$SCRIPT_DIR/.venv"

# Load .env
if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
else
    echo "Error: .env file not found. Run ./setup.sh first." >&2
    exit 1
fi

# Verify credentials
if [[ -z "$ZOOM_CLIENT_ID" || -z "$ZOOM_CLIENT_SECRET" ]]; then
    echo "Error: Missing ZOOM_CLIENT_ID or ZOOM_CLIENT_SECRET in .env" >&2
    exit 1
fi

# Use venv Python if available, otherwise system Python
if [[ -f "$VENV_DIR/bin/python3" ]]; then
    PYTHON="$VENV_DIR/bin/python3"
else
    PYTHON="python3"
fi

cd "$SCRIPT_DIR"
exec "$PYTHON" zoom_server.py
