"""Shared-space tools: list and detail-with-include."""
from typing import Any, Dict, List

from .dispatcher import paginate_all
from .endpoints import API_BASE


async def list_shared_spaces(oauth_handler) -> List[Dict[str, Any]]:
    headers = oauth_handler.get_auth_headers()
    return await paginate_all(
        "GET",
        f"{API_BASE}/chat/spaces",
        items_key="spaces",
        headers=headers,
    )


async def get_shared_space(
    oauth_handler, space_id: str, include: str = "detail"
) -> Dict[str, Any]:
    headers = oauth_handler.get_auth_headers()
    out: Dict[str, Any] = {}
    if include in ("detail", "all"):
        r = await oauth_handler.make_authenticated_request(
            "GET", f"{API_BASE}/chat/spaces/{space_id}",
        )
        if r.status_code != 200:
            raise RuntimeError(f"Shared space fetch failed: HTTP {r.status_code}")
        out["detail"] = r.json()
    if include in ("channels", "all"):
        out["channels"] = await paginate_all(
            "GET",
            f"{API_BASE}/chat/spaces/{space_id}/channels",
            items_key="channels",
            headers=headers,
        )
    if include in ("members", "all"):
        out["members"] = await paginate_all(
            "GET",
            f"{API_BASE}/chat/spaces/{space_id}/members",
            items_key="members",
            headers=headers,
        )
    return out
