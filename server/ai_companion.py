"""AI Companion search and ask. Replaces manual cross-channel fan-out."""
from typing import Any, Dict, List, Optional

from .endpoints import API_BASE

_SCOPE_MAP: Dict[Optional[str], List[str]] = {
    "chat": ["team_chat"],
    "meetings": ["meeting"],
    "docs": ["zoom_doc"],
    "all": ["team_chat", "meeting", "zoom_doc"],
    None: ["team_chat", "meeting", "zoom_doc"],
}


def scope_to_sources(scope: Optional[str]) -> List[str]:
    return list(_SCOPE_MAP.get(scope, _SCOPE_MAP["all"]))


def _build_body(extra: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in extra.items() if v is not None}


async def search(
    oauth_handler,
    *,
    query: str,
    scope: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    max_results: int = 50,
) -> Dict[str, Any]:
    if not query or not query.strip():
        raise ValueError("query is required")
    body = _build_body(
        {
            "query": query,
            "sources": scope_to_sources(scope),
            "from": from_date,
            "to": to_date,
            "limit": max_results,
        }
    )
    r = await oauth_handler.make_authenticated_request(
        "POST", f"{API_BASE}/ai_companion/search", json=body,
    )
    if r.status_code == 403:
        raise RuntimeError(
            "AI Companion is not enabled for this account. "
            "Ask your Zoom admin to enable it."
        )
    if r.status_code != 200:
        raise RuntimeError(
            f"AI Companion search failed: HTTP {r.status_code}: {r.text}"
        )
    return r.json()


async def ask(
    oauth_handler,
    *,
    question: str,
    scope: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> Dict[str, Any]:
    if not question or not question.strip():
        raise ValueError("question is required")
    body = _build_body(
        {
            "question": question,
            "sources": scope_to_sources(scope),
            "from": from_date,
            "to": to_date,
        }
    )
    r = await oauth_handler.make_authenticated_request(
        "POST", f"{API_BASE}/ai_companion/ask", json=body,
    )
    if r.status_code == 403:
        raise RuntimeError(
            "AI Companion is not enabled for this account. "
            "Ask your Zoom admin to enable it."
        )
    if r.status_code != 200:
        raise RuntimeError(
            f"AI Companion ask failed: HTTP {r.status_code}: {r.text}"
        )
    return r.json()
