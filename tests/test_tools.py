"""Smoke tests for ZoomTools registration and dispatch."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from server import http_client
from server.cache.store import CacheStore
from server.endpoints import ENDPOINTS
from server.oauth import ZoomOAuthHandler
from server.token_store import TokenStore
from server.tools import ZoomTools


@pytest.fixture(autouse=True)
async def _reset_client():
    yield
    await http_client.close_client()


@pytest.fixture
def authed_oauth(tmp_path):
    store = TokenStore(tmp_path / "tok.enc", tmp_path / "tok.key")
    store.save("AT", "RT", datetime.now() + timedelta(hours=1))
    return ZoomOAuthHandler(
        client_id="CID",
        token_store=store,
        redirect_uri="http://localhost:53682/oauth/callback",
    )


@pytest.fixture
def cache(tmp_path):
    return CacheStore(tmp_path / "cache.db")


def test_list_tools_returns_21(authed_oauth, cache):
    """v2.2.6: 21 tools after removing 4 unimplementable on the
    User-managed PKCE OAuth app this connector ships:
    - zoom_search_ai, zoom_search_ask (no public Zoom REST URL)
    - zoom_message_mentions (no public Zoom REST URL)
    - zoom_meeting_summary_list (Zoom requires :admin scope only
      available to Server-to-Server OAuth apps)"""
    tools = ZoomTools(authed_oauth, cache).list_tools()
    assert len(tools) == 21
    assert all(hasattr(t, "name") for t in tools)
    assert all(hasattr(t, "description") for t in tools)
    names = {t.name for t in tools}
    for unimplementable in (
        "zoom_search_ai",
        "zoom_search_ask",
        "zoom_message_mentions",
        "zoom_meeting_summary_list",
    ):
        assert unimplementable not in names, (
            f"{unimplementable} cannot work on User-managed OAuth"
        )


def test_list_tools_names_match_endpoints(authed_oauth, cache):
    tools = ZoomTools(authed_oauth, cache).list_tools()
    expected = {ep["name"] for ep in ENDPOINTS}
    actual = {t.name for t in tools}
    assert actual == expected


def test_auth_tools_present(authed_oauth, cache):
    tools = ZoomTools(authed_oauth, cache).list_tools()
    names = {t.name for t in tools}
    assert "zoom_auth_login" in names
    assert "zoom_auth_logout" in names


def test_tool_annotations_group_correctly(authed_oauth, cache):
    """Claude Desktop groups tools by readOnly/destructive hints."""
    tools = ZoomTools(authed_oauth, cache).list_tools()
    by_name = {t.name: t for t in tools}

    # zoom_auth_logout: destructive (wipes local state)
    logout_anns = by_name["zoom_auth_logout"].annotations
    assert logout_anns.readOnlyHint is False
    assert logout_anns.destructiveHint is True

    # zoom_auth_login: writes (saves tokens) but not destructive
    login_anns = by_name["zoom_auth_login"].annotations
    assert login_anns.readOnlyHint is False
    assert login_anns.destructiveHint is False

    # Every other tool is read-only
    for name, tool in by_name.items():
        if name in ("zoom_auth_login", "zoom_auth_logout"):
            continue
        anns = tool.annotations
        assert anns is not None, f"{name} missing annotations"
        assert anns.readOnlyHint is True, f"{name} should be readOnlyHint=True"
        assert anns.destructiveHint is False, (
            f"{name} should be destructiveHint=False"
        )


def test_legacy_tool_aliases_dispatch_to_new_handlers(authed_oauth, cache):
    """An MCP host with a stale tool-list cache may send pre-rename names.
    Those should still resolve to the right handler, not "Unknown tool"."""
    from server.tools import _LEGACY_TOOL_ALIASES, ZoomTools

    # Every legacy name must map to a current tool that exists in ENDPOINTS
    tools = ZoomTools(authed_oauth, cache).list_tools()
    current_names = {t.name for t in tools}
    for old, new in _LEGACY_TOOL_ALIASES.items():
        assert new in current_names, (
            f"Alias {old!r} -> {new!r}, but {new!r} is not a registered tool"
        )


@pytest.mark.asyncio
async def test_legacy_alias_for_revoke_works(authed_oauth, cache, tmp_path):
    """Calling the OLD name 'zoom_revoke_authentication' still wipes state."""
    cache.put_channels([{"id": "c1", "name": "x", "type": 3}])
    tools = ZoomTools(authed_oauth, cache)
    out = await tools.call_tool("zoom_revoke_authentication", {})
    assert "revoked" in out[0]["text"].lower()
    assert authed_oauth.token_store.load() is None


@pytest.mark.asyncio
async def test_legacy_alias_for_authenticate_when_already_valid(
    authed_oauth, cache
):
    """Calling old 'zoom_authenticate' still routes to the auth handler."""
    out = await ZoomTools(authed_oauth, cache).call_tool(
        "zoom_authenticate", {}
    )
    assert "Already authenticated" in out[0]["text"]


def test_tool_annotations_split_into_three_groups(authed_oauth, cache):
    """Confirm exact bucket counts: 19 read-only, 1 write, 1 destructive."""
    tools = ZoomTools(authed_oauth, cache).list_tools()
    read_only = [t for t in tools if t.annotations.readOnlyHint is True]
    write = [
        t for t in tools
        if t.annotations.readOnlyHint is False
        and t.annotations.destructiveHint is False
    ]
    destructive = [
        t for t in tools if t.annotations.destructiveHint is True
    ]
    assert len(read_only) == 19
    assert len(write) == 1
    assert len(destructive) == 1
    assert write[0].name == "zoom_auth_login"
    assert destructive[0].name == "zoom_auth_logout"


@pytest.mark.asyncio
async def test_call_tool_unknown_returns_error(authed_oauth, cache):
    out = await ZoomTools(authed_oauth, cache).call_tool("zoom_nope", {})
    assert "Unknown tool" in out[0]["text"]


@pytest.mark.asyncio
async def test_call_tool_missing_required_arg(authed_oauth, cache):
    out = await ZoomTools(authed_oauth, cache).call_tool(
        "zoom_search_messages", {}
    )
    assert "Missing required argument: query" in out[0]["text"]


@pytest.mark.asyncio
async def test_revoke_clears_tokens_and_cache(authed_oauth, cache, tmp_path):
    cache.put_channels([{"id": "c1", "name": "x", "type": 3}])
    tools = ZoomTools(authed_oauth, cache)
    out = await tools.call_tool("zoom_auth_logout", {})
    assert "revoked" in out[0]["text"].lower()
    assert authed_oauth.token_store.load() is None
    assert cache.get_channels() == []


@pytest.mark.asyncio
async def test_authenticate_skips_when_already_valid(authed_oauth, cache):
    out = await ZoomTools(authed_oauth, cache).call_tool(
        "zoom_auth_login", {}
    )
    assert "Already authenticated" in out[0]["text"]


@pytest.mark.asyncio
async def test_whoami_caches_in_memory(authed_oauth, cache):
    authed_oauth.make_authenticated_request = AsyncMock(
        return_value=httpx.Response(
            200, json={"id": "U1", "display_name": "Alex", "email": "a@b.com"}
        )
    )
    tools = ZoomTools(authed_oauth, cache)
    out1 = await tools.call_tool("zoom_auth_whoami", {})
    out2 = await tools.call_tool("zoom_auth_whoami", {})
    assert "Alex" in out1[0]["text"]
    assert "Alex" in out2[0]["text"]
    # second call should not have triggered another HTTP request
    assert authed_oauth.make_authenticated_request.call_count == 1


@pytest.mark.asyncio
async def test_resolve_finds_channel_by_name(authed_oauth, cache):
    cache.put_channels([{"id": "C1", "name": "general", "type": 3}])
    out = await ZoomTools(authed_oauth, cache).call_tool(
        "zoom_auth_resolve", {"query": "general", "kind": "channel"}
    )
    text = out[0]["text"]
    assert "channel" in text.lower()
    assert "C1" in text


@pytest.mark.asyncio
async def test_chat_channels_returns_cached(authed_oauth, cache):
    cache.put_channels(
        [
            {"id": "C1", "name": "general", "type": 3},
            {"id": "C2", "name": "devs", "type": 1, "starred": True},
        ]
    )
    out = await ZoomTools(authed_oauth, cache).call_tool(
        "zoom_chat_channels", {}
    )
    assert '"count": 2' in out[0]["text"]


@pytest.mark.asyncio
async def test_chat_channels_starred_filter(authed_oauth, cache):
    cache.put_channels(
        [
            {"id": "C1", "name": "general", "type": 3, "starred": False},
            {"id": "C2", "name": "devs", "type": 1, "starred": True},
        ]
    )
    out = await ZoomTools(authed_oauth, cache).call_tool(
        "zoom_chat_channels", {"starred_only": True}
    )
    assert '"count": 1' in out[0]["text"]
    assert "devs" in out[0]["text"]
