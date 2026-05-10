#!/usr/bin/env python3
"""Local diagnostic: call the endpoints the deployed connector is 400-ing on
and print the full Zoom error body.

Loads the encrypted access token from the deployed install location
(~/Library/Application Support/zoom-mcp/) and makes raw httpx calls so
we can see what Zoom is actually saying — bypassing the bug 3 swallow
in the *deployed* code.

Run from the worktree root:  python3 scripts/diag_endpoints.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

# Make the worktree's `server` package importable when this script is
# invoked from the worktree root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.token_store import TokenStore  # noqa: E402

import httpx  # noqa: E402

API_BASE = "https://api.zoom.us/v2"
TOKEN_DIR = Path.home() / "Library" / "Application Support" / "zoom-mcp"


async def probe(client: httpx.AsyncClient, headers: dict, label: str, method: str,
                path: str, **kwargs) -> None:
    url = f"{API_BASE}{path}"
    try:
        r = await client.request(method, url, headers=headers, **kwargs)
    except Exception as e:
        print(f"\n=== {label}\nURL: {url}\nTRANSPORT ERROR: {e}\n")
        return
    body = r.text or ""
    print(f"\n=== {label}\n{method} {r.request.url}")
    print(f"HTTP {r.status_code}")
    print(f"BODY: {body[:1500]}")


async def main() -> int:
    store = TokenStore(TOKEN_DIR / "tokens.enc", TOKEN_DIR / "tokens.key")
    data = store.load()
    if not data or not data.get("access_token"):
        print("No tokens loaded — is the deployed connector authenticated?",
              file=sys.stderr)
        return 2
    print(f"Token loaded. Scope: {data.get('scope')}")
    print(f"Token type: {data.get('token_type')}, expires_at: {data.get('expires_at')}")
    headers = {
        "Authorization": f"{data.get('token_type', 'Bearer')} {data['access_token']}",
        "User-Agent": "zoom-mcp-diag/1.0",
    }
    import certifi  # ships in the MCPB; locally usually present too
    async with httpx.AsyncClient(
        verify=certifi.where(),
        timeout=httpx.Timeout(30.0, connect=10.0),
    ) as client:
        # Reference: known-good
        await probe(client, headers, "users/me (reference: works)", "GET", "/users/me")

        # The 400-ing meeting endpoints
        await probe(client, headers, "users/me/meetings type=scheduled (no dates)",
                    "GET", "/users/me/meetings",
                    params={"type": "scheduled", "page_size": 30})
        await probe(client, headers, "users/me/meetings type=upcoming (no dates)",
                    "GET", "/users/me/meetings",
                    params={"type": "upcoming", "page_size": 30})
        await probe(client, headers, "users/me/meetings type=live (no dates)",
                    "GET", "/users/me/meetings",
                    params={"type": "live", "page_size": 30})
        await probe(client, headers, "users/me/meetings type=previous_meetings 30d",
                    "GET", "/users/me/meetings",
                    params={"type": "previous_meetings",
                            "from": "2026-04-10", "to": "2026-05-10",
                            "page_size": 30})
        # No type at all (Zoom default = live)
        await probe(client, headers, "users/me/meetings (no params)",
                    "GET", "/users/me/meetings", params={"page_size": 30})

        # meeting_summaries
        await probe(client, headers, "meetings/meeting_summaries 30d",
                    "GET", "/meetings/meeting_summaries",
                    params={"from": "2026-04-10", "to": "2026-05-10",
                            "page_size": 30})
        await probe(client, headers, "meetings/meeting_summaries no params",
                    "GET", "/meetings/meeting_summaries",
                    params={"page_size": 30})

        # search-mode chat: a real word, with a sample channel id and date range
        sample_channel_id = os.environ.get("DIAG_CHANNEL_ID")
        if sample_channel_id:
            await probe(client, headers,
                        "chat search_type=message search_key=test (with dates)",
                        "GET", "/chat/users/me/messages",
                        params={"search_type": "message",
                                "search_key": "test",
                                "to_channel": sample_channel_id,
                                "from": "2026-04-10",
                                "to": "2026-05-10",
                                "page_size": 50})
            await probe(client, headers,
                        "chat search_type=message search_key=test (no dates)",
                        "GET", "/chat/users/me/messages",
                        params={"search_type": "message",
                                "search_key": "test",
                                "to_channel": sample_channel_id,
                                "page_size": 50})
            # browse mode for comparison
            await probe(client, headers,
                        "chat browse mode (no search_*)",
                        "GET", "/chat/users/me/messages",
                        params={"to_channel": sample_channel_id,
                                "from": "2026-05-09",
                                "to": "2026-05-10",
                                "page_size": 10})
        else:
            print("\n(Skipping search-mode probes — set DIAG_CHANNEL_ID env var "
                  "to a real channel ID to test.)")

        # AI Companion (already known to be 404 publicly)
        await probe(client, headers, "ai_companion/search (known 404)",
                    "POST", "/ai_companion/search",
                    json={"query": "test", "sources": ["team_chat"]})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
