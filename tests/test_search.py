from unittest.mock import AsyncMock

import httpx
import pytest

from server import http_client, search


@pytest.fixture(autouse=True)
async def _reset_client():
    yield
    await http_client.close_client()


@pytest.mark.asyncio
async def test_search_rejects_empty_query():
    oauth = AsyncMock()
    with pytest.raises(ValueError):
        await search.search_messages(
            oauth, channels=[], contacts=[], query=""
        )


@pytest.mark.asyncio
async def test_search_fans_out_across_channels(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(
            "https://api.zoom.us/v2/chat/users/me/messages",
            params={
                "search_type": "message",
                "search_key": "Q3",
                "page_size": 50,
                "to_channel": "C1",
            },
        ),
        json={
            "messages": [
                {"id": "m1", "message": "Q3 plans", "date_time": "2026-04-10T10:00:00Z"}
            ]
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(
            "https://api.zoom.us/v2/chat/users/me/messages",
            params={
                "search_type": "message",
                "search_key": "Q3",
                "page_size": 50,
                "to_channel": "C2",
            },
        ),
        json={
            "messages": [
                {"id": "m2", "message": "Q3 review", "date_time": "2026-05-01T10:00:00Z"}
            ]
        },
    )
    oauth = AsyncMock()
    oauth.get_auth_headers = lambda: {"Authorization": "Bearer X"}
    out = await search.search_messages(
        oauth,
        channels=[{"id": "C1", "name": "general"}, {"id": "C2", "name": "devs"}],
        contacts=[],
        query="Q3",
    )
    assert out["scopes_searched"] == 2
    assert len(out["results"]) == 2
    # Sorted by date_time DESC — C2's message comes first
    assert out["results"][0]["id"] == "m2"
    assert out["results"][1]["id"] == "m1"
    # Each tagged with its scope
    assert out["results"][0]["to_channel"] == "C2"


@pytest.mark.asyncio
async def test_search_channel_filter_substring(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(
            "https://api.zoom.us/v2/chat/users/me/messages",
            params={
                "search_type": "message",
                "search_key": "x",
                "page_size": 50,
                "to_channel": "C2",
            },
        ),
        json={"messages": []},
    )
    oauth = AsyncMock()
    oauth.get_auth_headers = lambda: {"Authorization": "Bearer X"}
    out = await search.search_messages(
        oauth,
        channels=[
            {"id": "C1", "name": "general"},
            {"id": "C2", "name": "devs"},
            {"id": "C3", "name": "design"},
        ],
        contacts=[],
        query="x",
        channel_filter="dev",
    )
    # Only "devs" matches "dev" substring
    assert out["scopes_searched"] == 1


@pytest.mark.asyncio
async def test_search_max_results_truncates(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(
            "https://api.zoom.us/v2/chat/users/me/messages",
            params={
                "search_type": "message",
                "search_key": "x",
                "page_size": 50,
                "to_channel": "C1",
            },
        ),
        json={
            "messages": [
                {"id": f"m{i}", "date_time": f"2026-05-0{i}T10:00:00Z"}
                for i in range(1, 6)
            ]
        },
    )
    oauth = AsyncMock()
    oauth.get_auth_headers = lambda: {"Authorization": "Bearer X"}
    out = await search.search_messages(
        oauth,
        channels=[{"id": "C1", "name": "x"}],
        contacts=[],
        query="x",
        max_results=2,
    )
    assert len(out["results"]) == 2
    assert out["total_found"] == 5
