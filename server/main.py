#!/usr/bin/env python3
"""Zoom MCP Server v2 entry point."""
import asyncio
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Prepend sibling-module path (so `server.*` resolves when run as a script)
_THIS_DIR = Path(__file__).resolve().parent
_PARENT_DIR = _THIS_DIR.parent
if str(_PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(_PARENT_DIR))

# Inside an MCPB bundle, vendored deps live under server/lib/py3XX/.
# Pick the right subdir for the running Python.
_PY_TAG = f"py3{sys.version_info.minor}"
_VER_DIR = _THIS_DIR / "lib" / _PY_TAG
if _VER_DIR.is_dir():
    if str(_VER_DIR) not in sys.path:
        sys.path.insert(0, str(_VER_DIR))
elif (_THIS_DIR / "lib").is_dir():
    # We're in a bundle but no matching py3XX dir — fall back to highest
    # available version. Native-extension wheels won't load across ABI
    # boundaries, but pure-Python imports might still work.
    _LIB_DIR = _THIS_DIR / "lib"
    available = sorted(
        (d for d in _LIB_DIR.iterdir()
         if d.is_dir() and d.name.startswith("py3")),
        key=lambda d: int(d.name[3:]) if d.name[3:].isdigit() else -1,
        reverse=True,
    )
    if available:
        sys.stderr.write(
            f"WARNING: zoom-mcp bundle has no wheels for {_PY_TAG} "
            f"(running Python {sys.version_info.major}.{sys.version_info.minor}). "
            f"Falling back to {available[0].name}; native-extension imports "
            f"(certifi, cryptography, pydantic_core) may fail. Rebuild the "
            f"bundle with --include-py {_PY_TAG[2:]} or upgrade/downgrade "
            f"your python3.\n"
        )
        sys.path.insert(0, str(available[0]))
    else:
        sys.stderr.write(
            f"FATAL: zoom-mcp bundle missing all py3XX wheel dirs.\n"
        )
# Backward-compatible flat layout (when not built per-version)
_FLAT_LIB = _THIS_DIR / "lib"
if _FLAT_LIB.is_dir() and str(_FLAT_LIB) not in sys.path:
    sys.path.append(str(_FLAT_LIB))

import mcp.server.stdio  # noqa: E402
from mcp.server import NotificationOptions, Server  # noqa: E402
from mcp.server.models import InitializationOptions  # noqa: E402

from server.cache.store import CacheStore  # noqa: E402
from server.log_filter import SensitiveFilter  # noqa: E402
from server.oauth import ZoomOAuthHandler  # noqa: E402
from server.paths import (  # noqa: E402
    cache_db_file,
    ensure_dirs,
    log_file,
    token_file,
    token_key_file,
)
from server.token_store import TokenStore  # noqa: E402
from server.tools import ZoomTools  # noqa: E402


def setup_logging() -> logging.Logger:
    ensure_dirs()
    logger = logging.getLogger("zoom-mcp")
    logger.setLevel(logging.INFO)
    fh = RotatingFileHandler(log_file(), maxBytes=10 * 1024 * 1024, backupCount=5)
    fh.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    fh.addFilter(SensitiveFilter())
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
    sh.addFilter(SensitiveFilter())
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def get_required_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.stderr.write(f"FATAL: env var {name} is required\n")
        sys.exit(1)
    return v


# Defaults bake in PortSwigger's Zoom dev app + Public Client OAuth (PKCE).
# Dev apps allow http://localhost callbacks; public client ID means no secret.
DEFAULT_CLIENT_ID = "EIQOYZ5wQBCSQk3a48lT6A"
# Port 53682: IANA dynamic range, matches gcloud SDK's OAuth callback
# port (proven low-conflict). Migrated from 8000 in v2.2.7 to avoid
# collision with common dev servers (jupyter/django/http.server).
DEFAULT_REDIRECT_URI = "http://localhost:53682/oauth/callback"


async def run() -> None:
    logger = setup_logging()
    logger.info("Zoom MCP server starting")

    # PKCE flow — no client_secret. Defaults bake in the PortSwigger Zoom
    # app + GitHub Pages bridge so Swiggers don't have to configure anything.
    client_id = os.environ.get("ZOOM_CLIENT_ID") or DEFAULT_CLIENT_ID
    redirect_uri = os.environ.get("ZOOM_REDIRECT_URI") or DEFAULT_REDIRECT_URI

    token_store = TokenStore(token_file(), token_key_file())
    oauth = ZoomOAuthHandler(
        client_id=client_id,
        token_store=token_store,
        redirect_uri=redirect_uri,
        logger=logger,
    )
    cache = CacheStore(cache_db_file())
    tools_api = ZoomTools(oauth_handler=oauth, cache=cache)
    server = Server("zoom-integration")

    # Eagerly trigger the browser auth flow on first launch if there's no
    # session yet. Runs concurrently with the MCP server so stdin/stdout
    # are not blocked. Subsequent launches with a refresh token are silent.
    asyncio.create_task(oauth.maybe_auth_on_startup())

    @server.list_tools()
    async def _list_tools():
        return tools_api.list_tools()

    @server.call_tool()
    async def _call_tool(name: str, args: dict):
        return await tools_api.call_tool(name, args or {})

    async with mcp.server.stdio.stdio_server() as (rs, ws):
        await server.run(
            rs,
            ws,
            InitializationOptions(
                server_name="zoom-integration",
                server_version="2.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
