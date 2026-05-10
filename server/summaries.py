"""Zoom AI Companion meeting summaries (per-meeting fetch only).

The `list_meeting_summaries` endpoint at /v2/meetings/meeting_summaries
demands `meeting:read:list_summaries:admin` — a `:admin` scope that's
only exposed to Server-to-Server OAuth apps, not the User-managed PKCE
app this connector uses. So we expose only the per-meeting fetcher
below; callers can iterate `zoom_meeting_list` + `zoom_meeting_summary_get`
for equivalent functionality on User-managed OAuth.

Required scope (must be enabled on the Zoom dev app):
  - meeting:read:summary  → get_meeting_summary
"""
from typing import Any, Dict

from .endpoints import API_BASE


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
