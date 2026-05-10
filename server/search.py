"""Cross-channel message search via parallel fan-out.

Replaces the originally planned AI Companion `search` endpoint, which
turns out not to exist publicly. Instead, fires Zoom's per-scope message
search across each channel (and DM thread, optionally) in parallel,
merges results, and sorts by recency.
"""
import asyncio
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx

from .endpoints import API_BASE
from .http_client import request_with_retry


_SEARCH_CONCURRENCY = 20
_PER_SCOPE_LIMIT = 50  # Zoom message-list page max


# Returned by _search_one alongside the items list: (items, error_string)
# error_string is None on success, otherwise a short, single-line summary
# of what went wrong (HTTP status + truncated body, or transport error
# message). The caller aggregates these to surface a representative
# sample to the user instead of silently swallowing.
_OneResult = Tuple[List[Dict[str, Any]], Optional[str]]


async def _search_one(
    sem: asyncio.Semaphore,
    headers: Dict[str, str],
    *,
    to_channel: Optional[str] = None,
    to_contact: Optional[str] = None,
    query: str,
    from_date: Optional[str],
    to_date: Optional[str],
) -> _OneResult:
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
        except httpx.RequestError as e:
            return [], f"transport: {type(e).__name__}: {e}"
        if r.status_code != 200:
            body = (r.text or "")[:200].replace("\n", " ").strip()
            return [], f"HTTP {r.status_code}: {body}"
        data = r.json()
        items = data.get("messages", [])
        for item in items:
            if to_channel and "to_channel" not in item:
                item["to_channel"] = to_channel
            if to_contact and "to_contact" not in item:
                item["to_contact"] = to_contact
        return items, None


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
      {
        "results": [...],
        "total_found": N,
        "scopes_searched": M,
        "scopes_errored": E,
        "sample_errors": [str, ...],   # up to 3 distinct error strings
      }
    """
    if not query or not query.strip():
        raise ValueError("query is required")
    q = query.strip()

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
                query=q,
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
                query=q,
                from_date=from_date,
                to_date=to_date,
            )
        )

    results: List[Union[_OneResult, BaseException]] = await asyncio.gather(
        *tasks, return_exceptions=True
    )
    merged: List[Dict[str, Any]] = []
    errors = 0
    sample_errors: List[str] = []
    seen_error_keys: set = set()
    for r in results:
        if isinstance(r, BaseException):
            errors += 1
            err_str = f"exception: {type(r).__name__}: {r}"
        else:
            items, err_str = r
            if err_str is None:
                merged.extend(items)
                continue
            errors += 1
        # Aggregate up to 3 *distinct* error fingerprints. Many channels
        # often return the same 400, so we de-dupe on the leading prefix
        # to keep the sample small but representative.
        key = err_str[:80]
        if key not in seen_error_keys and len(sample_errors) < 3:
            seen_error_keys.add(key)
            sample_errors.append(err_str)

    def _ts(m: Dict[str, Any]) -> str:
        return m.get("date_time") or ""

    merged.sort(key=_ts, reverse=True)
    truncated = merged[:max_results]

    return {
        "results": truncated,
        "total_found": len(merged),
        "scopes_searched": len(tasks),
        "scopes_errored": errors,
        "sample_errors": sample_errors,
    }
