"""Generic API dispatcher with auto-pagination and path-param substitution."""
from typing import Any, Dict, List, Optional

from .http_client import request_with_retry


def build_url(
    base: str, path: str, path_params: Optional[Dict[str, str]] = None
) -> str:
    if path_params:
        for k, v in path_params.items():
            path = path.replace(f"{{{k}}}", str(v))
    return f"{base.rstrip('/')}{path}"


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
            r.raise_for_status()
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
