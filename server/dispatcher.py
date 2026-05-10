"""Generic API dispatcher with auto-pagination and path-param substitution."""
import json
import re
from typing import Any, Dict, List, Optional

import httpx

from .http_client import request_with_retry


def build_url(
    base: str, path: str, path_params: Optional[Dict[str, str]] = None
) -> str:
    if path_params:
        for k, v in path_params.items():
            path = path.replace(f"{{{k}}}", str(v))
    return f"{base.rstrip('/')}{path}"


def format_zoom_error(status_code: int, body_text: str) -> str:
    """Turn a Zoom 4xx body into a single-line, actionable message.

    Zoom returns errors as JSON like
    `{"code":4711,"message":"Invalid access token, does not contain
    scopes:[meeting:read:list_meetings, meeting:read:list_meetings:admin]."}`
    The 4711 case is by far the most common cause of 400s for this
    connector — the Zoom OAuth app is missing a scope. Surface that
    in a way that tells the user what to do next.
    """
    body_text = (body_text or "").strip()
    body_short = body_text[:500]
    try:
        data = json.loads(body_text)
    except (ValueError, TypeError):
        return f"HTTP {status_code}: {body_short}"
    code = data.get("code")
    msg = (data.get("message") or "").strip()
    if code == 4711:
        scopes = re.findall(r"[a-z_]+:[a-z_:]+", msg)
        scope_str = ", ".join(scopes) if scopes else "(scope name not parseable)"
        return (
            f"HTTP 400 (Zoom code 4711): Zoom OAuth app missing scope. "
            f"Required: [{scope_str}]. Fix: a Zoom Marketplace admin must "
            f"add the missing scope(s) to the dev app and the user must "
            f"re-authenticate (zoom_auth_logout, then zoom_auth_login). "
            f"Original Zoom message: {msg}"
        )
    if code == 2300:
        return (
            f"HTTP {status_code} (Zoom code 2300): "
            f"This Zoom API endpoint is not exposed by Zoom. "
            f"Original Zoom message: {msg}"
        )
    if code is not None:
        return f"HTTP {status_code} (Zoom code {code}): {msg}"
    return f"HTTP {status_code}: {body_short}"


async def paginate_all(
    method: str,
    url: str,
    *,
    items_key: str,
    headers: Dict[str, str],
    params: Optional[Dict[str, Any]] = None,
    max_items: Optional[int] = 1000,
    page_size: int = 100,
) -> List[Any]:
    """Chase next_page_token until exhausted, returning aggregated items."""
    params = dict(params or {})
    params.setdefault("page_size", page_size)
    items: List[Any] = []
    next_token: Optional[str] = None
    while True:
        if next_token:
            params["next_page_token"] = next_token
        r = await request_with_retry(method, url, headers=headers, params=params)
        if r.status_code != 200:
            # Surface the response body so callers can see what Zoom actually
            # said — `r.raise_for_status()` discards r.text and produces only
            # a generic "400 Bad Request" string, which makes debugging
            # impossible.
            raise httpx.HTTPStatusError(
                format_zoom_error(r.status_code, r.text),
                request=r.request,
                response=r,
            )
        data = r.json()
        page_items = data.get(items_key, [])
        items.extend(page_items)
        next_token = data.get("next_page_token") or None
        if not next_token:
            break
        if max_items is not None and len(items) >= max_items:
            return items[:max_items]
    if max_items is not None:
        return items[:max_items]
    return items
