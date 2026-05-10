#!/usr/bin/env bash
# Run the server from source for local iteration. Loads .env if present.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
exec .venv/bin/python -m server.main
