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
        redirect_uri="http://localhost:8000/oauth/callback",
    )


@pytest.fixture
def cache(tmp_path):
    return CacheStore(tmp_path / "cache.db")


def test_list_tools_returns_20(authed_oauth, cache):
    tools = ZoomTools(authed_oauth, cache).list_tools()
    assert len(tools) == 20
    assert all(hasattr(t, "name") for t in tools)
    assert all(hasattr(t, "description") for t in tools)


def test_list_tools_names_match_endpoints(authed_oauth, cache):
    tools = ZoomTools(authed_oauth, cache).list_tools()
    expected = {ep["name"] for ep in ENDPOINTS}
    actual = {t.name for t in tools}
    assert actual == expected


def test_auth_tools_present(authed_oauth, cache):
    tools = ZoomTools(authed_oauth, cache).list_tools()
    names = {t.name for t in tools}
    assert "zoom_authenticate" in names
    assert "zoom_revoke_authentication" in names


@pytest.mark.asyncio
async def test_call_tool_unknown_returns_error(authed_oauth, cache):
    out = await ZoomTools(authed_oauth, cache).call_tool("zoom_nope", {})
    assert "Unknown tool" in out[0]["text"]


@pytest.mark.asyncio
async def test_call_tool_missing_required_arg(authed_oauth, cache):
    out = await ZoomTools(authed_oauth, cache).call_tool("zoom_search_messages", {})
    assert "Missing required argument: query" in out[0]["text"]


@pytest.mark.asyncio
async def test_revoke_clears_tokens_and_cache(authed_oauth, cache, tmp_path):
    cache.put_channels([{"id": "c1", "name": "x", "type": 3}])
    tools = ZoomTools(authed_oauth, cache)
    out = await tools.call_tool("zoom_revoke_authentication", {})
    assert "revoked" in out[0]["text"].lower()
    assert authed_oauth.token_store.load() is None
    assert cache.get_channels() == []


@pytest.mark.asyncio
async def test_authenticate_skips_when_already_valid(authed_oauth, cache):
    out = await ZoomTools(authed_oauth, cache).call_tool(
        "zoom_authenticate", {}
    )
    assert "Already authenticated" in out[0]["text"]


@pytest.mark.asyncio
async def test_get_my_info_caches_in_memory(authed_oauth, cache):
    authed_oauth.make_authenticated_request = AsyncMock(
        return_value=httpx.Response(
            200, json={"id": "U1", "display_name": "Alex", "email": "a@b.com"}
        )
    )
    tools = ZoomTools(authed_oauth, cache)
    out1 = await tools.call_tool("zoom_get_my_info", {})
    out2 = await tools.call_tool("zoom_get_my_info", {})
    assert "Alex" in out1[0]["text"]
    assert "Alex" in out2[0]["text"]
    # second call should not have triggered another HTTP request
    assert authed_oauth.make_authenticated_request.call_count == 1


@pytest.mark.asyncio
async def test_resolve_finds_channel_by_name(authed_oauth, cache):
    cache.put_channels([{"id": "C1", "name": "general", "type": 3}])
    out = await ZoomTools(authed_oauth, cache).call_tool(
        "zoom_resolve", {"query": "general", "kind": "channel"}
    )
    text = out[0]["text"]
    assert "channel" in text.lower()
    assert "C1" in text


@pytest.mark.asyncio
async def test_list_channels_returns_cached(authed_oauth, cache):
    cache.put_channels(
        [
            {"id": "C1", "name": "general", "type": 3},
            {"id": "C2", "name": "devs", "type": 1, "starred": True},
        ]
    )
    out = await ZoomTools(authed_oauth, cache).call_tool(
        "zoom_list_channels", {}
    )
    assert '"count": 2' in out[0]["text"]


@pytest.mark.asyncio
async def test_list_channels_starred_filter(authed_oauth, cache):
    cache.put_channels(
        [
            {"id": "C1", "name": "general", "type": 3, "starred": False},
            {"id": "C2", "name": "devs", "type": 1, "starred": True},
        ]
    )
    out = await ZoomTools(authed_oauth, cache).call_tool(
        "zoom_list_channels", {"starred_only": True}
    )
    assert '"count": 1' in out[0]["text"]
    assert "devs" in out[0]["text"]
