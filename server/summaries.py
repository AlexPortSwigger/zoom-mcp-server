"""Zoom AI Companion meeting summaries.

These are the *real* AI Companion APIs (`meeting_summary:read:summary`).
The `/ai_companion/search` and `/ai_companion/ask` endpoints I originally
planned do not exist publicly.
"""
from typing import Any, Dict, List, Optional

from .dispatcher import paginate_all
from .endpoints import API_BASE


async def list_meeting_summaries(
    oauth_handler,
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    headers = oauth_handler.get_auth_headers()
    params: Dict[str, Any] = {}
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    return await paginate_all(
        "GET",
        f"{API_BASE}/meetings/meeting_summaries",
        items_key="summaries",
        headers=headers,
        params=params,
    )


async def get_meeting_summary(oauth_handler, meeting_id: str) -> Dict[str, Any]:
    r = await oauth_handler.make_authenticated_request(
        "GET",
        f"{API_BASE}/meetings/{meeting_id}/meeting_summary",
    )
    if r.status_code == 404:
        raise RuntimeError(
            "No AI Companion summary available for this meeting. "
            "Either the meeting wasn't recorded, AI Companion wasn't "
            "enabled, or the summary is still being generated."
        )
    if r.status_code != 200:
        raise RuntimeError(
            f"Get meeting summary failed: HTTP {r.status_code}: {r.text}"
        )
    return r.json()
