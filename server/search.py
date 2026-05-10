"""Cross-channel message search via parallel fan-out.

Replaces the originally planned AI Companion `search` endpoint, which
turns out not to exist publicly. Instead, fires Zoom's per-scope message
search across each channel (and DM thread, optionally) in parallel,
merges results, and sorts by recency.
"""
import asyncio
from typing import Any, Dict, List, Optional

import httpx

from .endpoints import API_BASE
from .http_client import request_with_retry


_SEARCH_CONCURRENCY = 20
_PER_SCOPE_LIMIT = 50  # Zoom message-list page max


async def _search_one(
    sem: asyncio.Semaphore,
    headers: Dict[str, str],
    *,
    to_channel: Optional[str] = None,
    to_contact: Optional[str] = None,
    query: str,
    from_date: Optional[str],
    to_date: Optional[str],
) -> List[Dict[str, Any]]:
    async with sem:
        params: Dict[str, Any] = {
            "search_type": "message",
            "search_key": query,
            "page_size": _PER_SCOPE_LIMIT,
        }
        if to_channel:
            params["to_channel"] = to_channel
        if to_contact:
            params["to_contact"] = to_contact
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        try:
            r = await request_with_retry(
                "GET",
                f"{API_BASE}/chat/users/me/messages",
                headers=headers,
                params=params,
            )
        except httpx.RequestError:
            return []
        if r.status_code != 200:
            return []
        data = r.json()
        items = data.get("messages", [])
        # Tag each item with its scope so callers can show channel context
        for item in items:
            if to_channel and "to_channel" not in item:
                item["to_channel"] = to_channel
            if to_contact and "to_contact" not in item:
                item["to_contact"] = to_contact
        return items


async def search_messages(
    oauth_handler,
    *,
    channels: List[Dict[str, Any]],
    contacts: List[Dict[str, Any]],
    query: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    channel_filter: Optional[str] = None,
    max_results: int = 100,
) -> Dict[str, Any]:
    """Fan out scoped searches across channels and DM contacts in parallel.

    Returns:
      {"results": [...], "total_found": N, "scopes_searched": M, "scopes_errored": E}
    """
    if not query or not query.strip():
        raise ValueError("query is required")

    headers = oauth_handler.get_auth_headers()

    target_channels = channels
    if channel_filter:
        cf = channel_filter.lower()
        target_channels = [
            c for c in channels if cf in (c.get("name") or "").lower()
        ]

    sem = asyncio.Semaphore(_SEARCH_CONCURRENCY)
    tasks = []
    for c in target_channels:
        tasks.append(
            _search_one(
                sem,
                headers,
                to_channel=c["id"],
                query=query,
                from_date=from_date,
                to_date=to_date,
            )
        )
    for ct in contacts:
        tasks.append(
            _search_one(
                sem,
                headers,
                to_contact=ct["id"],
                query=query,
                from_date=from_date,
                to_date=to_date,
            )
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)
    merged: List[Dict[str, Any]] = []
    errors = 0
    for r in results:
        if isinstance(r, Exception):
            errors += 1
            continue
        merged.extend(r)

    # Sort by date_time DESC; missing timestamps sort last
    def _ts(m: Dict[str, Any]) -> str:
        return m.get("date_time") or ""

    merged.sort(key=_ts, reverse=True)
    truncated = merged[:max_results]

    return {
        "results": truncated,
        "total_found": len(merged),
        "scopes_searched": len(tasks),
        "scopes_errored": errors,
    }
