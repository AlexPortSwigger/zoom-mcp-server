"""Message-listing tools (channel history, threads, single message lookup, pinned, bookmarks, mention groups)."""
from typing import Any, Dict, List, Optional

from .dispatcher import paginate_all
from .endpoints import API_BASE


def _scope_params(
    channel_id: Optional[str], contact_id: Optional[str]
) -> Dict[str, str]:
    if channel_id:
        return {"to_channel": channel_id}
    if contact_id:
        return {"to_contact": contact_id}
    return {}


async def get_channel_history(
    oauth_handler,
    *,
    channel_id: Optional[str] = None,
    contact_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    max_messages: int = 500,
) -> List[Dict[str, Any]]:
    if not channel_id and not contact_id:
        raise ValueError("Either channel_id or contact_id is required")
    headers = oauth_handler.get_auth_headers()
    params = _scope_params(channel_id, contact_id)
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    return await paginate_all(
        "GET",
        f"{API_BASE}/chat/users/me/messages",
        items_key="messages",
        headers=headers,
        params=params,
        max_items=max_messages,
        page_size=50,
    )


async def get_thread(
    oauth_handler,
    *,
    message_id: str,
    channel_id: Optional[str] = None,
    contact_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    headers = oauth_handler.get_auth_headers()
    params = _scope_params(channel_id, contact_id)
    return await paginate_all(
        "GET",
        f"{API_BASE}/chat/users/me/messages/{message_id}",
        items_key="messages",
        headers=headers,
        params=params,
        page_size=50,
    )


async def get_message(
    oauth_handler,
    *,
    message_id: str,
    channel_id: Optional[str] = None,
    contact_id: Optional[str] = None,
) -> Dict[str, Any]:
    params = _scope_params(channel_id, contact_id)
    r = await oauth_handler.make_authenticated_request(
        "GET",
        f"{API_BASE}/chat/users/me/messages/{message_id}",
        params=params,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Get message failed: HTTP {r.status_code}: {r.text}")
    return r.json()


async def list_pinned_messages(
    oauth_handler, channel_id: str
) -> List[Dict[str, Any]]:
    headers = oauth_handler.get_auth_headers()
    return await paginate_all(
        "GET",
        f"{API_BASE}/chat/channels/{channel_id}/pinned",
        items_key="messages",
        headers=headers,
    )


async def list_bookmarks(oauth_handler) -> List[Dict[str, Any]]:
    headers = oauth_handler.get_auth_headers()
    return await paginate_all(
        "GET",
        f"{API_BASE}/chat/messages/bookmarks",
        items_key="bookmarks",
        headers=headers,
    )


