"""Cross-channel message search.

Two modes, both via parallel fan-out:

- search_messages: Zoom-native keyword search via search_type=message
  on /chat/users/me/messages. Fast (one round-trip per scope) but Zoom
  caps the time window to ~24h regardless of from/to params. Use this
  for "what was said today/yesterday".

- search_history: deep search via browse-mode history fetch + client-side
  keyword filter. Slower (paginates each scope's messages) but honours
  the full date range. Use this when search_messages returns nothing
  for a query that should match older content (the "I know it's
  there, native Zoom search finds it" case).
"""
import asyncio
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx

from . import messages
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
            params["from"] = messages.to_zoom_ts(from_date)
        if to_date:
            params["to"] = messages.to_zoom_ts(to_date, end_of_day=True)

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

    out: Dict[str, Any] = {
        "results": truncated,
        "total_found": len(merged),
        "scopes_searched": len(tasks),
        "scopes_errored": errors,
        "sample_errors": sample_errors,
        "mode": "fast",
    }
    # Auto-fallback hint: if no hits AND no errors, the most likely
    # explanation is Zoom's 24h server-side cap on keyword search hiding
    # older matches. Tell the caller to retry via zoom_search_history.
    # This makes the routing automatic from the LLM's perspective.
    if len(merged) == 0 and errors == 0:
        out["hint"] = (
            "0 hits with 0 errors. Zoom's keyword search is "
            "server-side capped to ~24 hours regardless of from_date/"
            "to_date. If the message you're looking for is older than "
            "yesterday, retry with `zoom_search_history` (same query, "
            "explicit from_date back as far as needed, optionally a "
            "sender_filter)."
        )
    return out


# ----------------------------------------------------------------------
# search_history — deep, client-side, no 24h cap
# ----------------------------------------------------------------------

# Browse mode pages 50 messages at a time; this caps per-scope traversal
# so a runaway active channel doesn't drag a search to a halt.
_HISTORY_MAX_MSGS_PER_SCOPE = 2000


async def _scan_one_history(
    sem: asyncio.Semaphore,
    oauth_handler,
    *,
    scope_kind: str,
    scope_id: str,
    scope_label: str,
    query_lower: str,
    sender_lower: Optional[str],
    from_date: Optional[str],
    to_date: Optional[str],
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Pull one scope's message history in [from_date, to_date], filter
    client-side, return the hits."""
    async with sem:
        try:
            msgs = await messages.get_channel_history(
                oauth_handler,
                channel_id=scope_id if scope_kind == "channel" else None,
                contact_id=scope_id if scope_kind == "contact" else None,
                from_date=from_date,
                to_date=to_date,
                max_messages=_HISTORY_MAX_MSGS_PER_SCOPE,
            )
        except httpx.HTTPStatusError as e:
            body = (e.response.text or "")[:200].replace("\n", " ").strip()
            return [], f"{scope_kind}={scope_label}: HTTP {e.response.status_code}: {body}"
        except httpx.RequestError as e:
            return [], f"{scope_kind}={scope_label}: transport: {type(e).__name__}: {e}"

        hits: List[Dict[str, Any]] = []
        for m in msgs:
            text = (m.get("message") or "").lower()
            if query_lower not in text:
                continue
            if sender_lower:
                sender = (m.get("sender") or "").lower()
                name = (m.get("sender_display_name") or "").lower()
                if sender_lower not in sender and sender_lower not in name:
                    continue
            # Tag with scope so the caller knows where each hit came from.
            if scope_kind == "channel":
                m.setdefault("to_channel", scope_id)
                m.setdefault("channel_name", scope_label)
            else:
                m.setdefault("to_contact", scope_id)
                m.setdefault("contact_name", scope_label)
            hits.append(m)
        return hits, None


async def search_history(
    oauth_handler,
    *,
    channels: List[Dict[str, Any]],
    contacts: List[Dict[str, Any]],
    query: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    sender_filter: Optional[str] = None,
    max_results: int = 100,
) -> Dict[str, Any]:
    """Deep keyword search via browse-mode history fetch + client-side
    filter. Honours the full from/to range — no 24h cap.

    Caller is responsible for narrowing `channels` and `contacts` to
    the right set before calling (e.g. starred-only, or filtered by a
    name substring) — this function will scan everything it's handed.
    """
    if not query or not query.strip():
        raise ValueError("query is required")
    q_lower = query.strip().lower()
    sf_lower = sender_filter.strip().lower() if sender_filter else None

    sem = asyncio.Semaphore(_SEARCH_CONCURRENCY)
    tasks = []
    for c in channels:
        tasks.append(
            _scan_one_history(
                sem, oauth_handler,
                scope_kind="channel",
                scope_id=c["id"],
                scope_label=c.get("name") or c["id"],
                query_lower=q_lower,
                sender_lower=sf_lower,
                from_date=from_date,
                to_date=to_date,
            )
        )
    for ct in contacts:
        tasks.append(
            _scan_one_history(
                sem, oauth_handler,
                scope_kind="contact",
                scope_id=ct["id"],
                scope_label=ct.get("display_name") or ct.get("email") or ct["id"],
                query_lower=q_lower,
                sender_lower=sf_lower,
                from_date=from_date,
                to_date=to_date,
            )
        )

    results: List[Union[Tuple[List[Dict[str, Any]], Optional[str]], BaseException]] = (
        await asyncio.gather(*tasks, return_exceptions=True)
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
            hits, err_str = r
            if err_str is None:
                merged.extend(hits)
                continue
            errors += 1
        key = err_str[:80]
        if key not in seen_error_keys and len(sample_errors) < 3:
            seen_error_keys.add(key)
            sample_errors.append(err_str)

    merged.sort(key=lambda m: m.get("date_time") or "", reverse=True)
    truncated = merged[:max_results]

    return {
        "results": truncated,
        "total_found": len(merged),
        "scopes_searched": len(tasks),
        "scopes_errored": errors,
        "sample_errors": sample_errors,
        "mode": "history",
    }
