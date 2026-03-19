#!/bin/bash

# Zoom MCP Server Wrapper
# Loads environment variables and starts the Zoom MCP server

set -e

# Resolve paths relative to this script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
else
    echo "Error: .env file not found at $ENV_FILE"
    echo "Copy .env.example to .env and add your Zoom credentials"
    exit 1
fi

# Verify required environment variables
if [[ -z "$ZOOM_CLIENT_ID" || -z "$ZOOM_CLIENT_SECRET" ]]; then
    echo "Error: Missing required Zoom environment variables"
    echo "Required: ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET"
    exit 1
fi

# Start the Zoom MCP server
cd "$SCRIPT_DIR"
exec python3 zoom_server.py
