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


@pytest.mark.asyncio
async def test_search_counts_non_200_as_errors_and_captures_body(httpx_mock):
    """Bug 1 fix: a 400 from a per-channel search must bump
    scopes_errored and include a sample of the Zoom error body in
    sample_errors. Pre-fix, non-200s silently returned [] so callers
    saw `total_found=0, scopes_errored=0` even when every call failed."""
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
        status_code=400,
        json={
            "code": 4711,
            "message": (
                "Invalid access token, does not contain "
                "scopes:[team_chat:read:list_user_messages]."
            ),
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
        status_code=400,
        json={
            "code": 4711,
            "message": (
                "Invalid access token, does not contain "
                "scopes:[team_chat:read:list_user_messages]."
            ),
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
    assert out["scopes_errored"] == 2
    assert out["total_found"] == 0
    # sample_errors must show what Zoom said so the user can diagnose
    assert len(out["sample_errors"]) >= 1
    blob = " ".join(out["sample_errors"])
    assert "400" in blob
    assert "4711" in blob
    assert "team_chat:read:list_user_messages" in blob


@pytest.mark.asyncio
async def test_search_dedupes_sample_errors(httpx_mock):
    """When all 1000+ channels return the same error, sample_errors
    should include the error once, not 1000 times."""
    for i in range(5):
        httpx_mock.add_response(
            method="GET",
            url=httpx.URL(
                "https://api.zoom.us/v2/chat/users/me/messages",
                params={
                    "search_type": "message",
                    "search_key": "x",
                    "page_size": 50,
                    "to_channel": f"C{i}",
                },
            ),
            status_code=400,
            json={"code": 4711, "message": "missing scope X"},
        )
    oauth = AsyncMock()
    oauth.get_auth_headers = lambda: {"Authorization": "Bearer X"}
    out = await search.search_messages(
        oauth,
        channels=[{"id": f"C{i}", "name": str(i)} for i in range(5)],
        contacts=[],
        query="x",
    )
    assert out["scopes_errored"] == 5
    # All identical → sample_errors capped, not 5 copies
    assert len(out["sample_errors"]) == 1


@pytest.mark.asyncio
async def test_search_mixes_success_and_failure(httpx_mock):
    """Mixed mode: some channels return 200, others 400. Successes are
    aggregated into results; failures are counted and sampled."""
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(
            "https://api.zoom.us/v2/chat/users/me/messages",
            params={
                "search_type": "message",
                "search_key": "x",
                "page_size": 50,
                "to_channel": "GOOD",
            },
        ),
        json={
            "messages": [
                {"id": "m1", "date_time": "2026-05-10T10:00:00Z"}
            ]
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(
            "https://api.zoom.us/v2/chat/users/me/messages",
            params={
                "search_type": "message",
                "search_key": "x",
                "page_size": 50,
                "to_channel": "BAD",
            },
        ),
        status_code=400,
        json={"code": 1234, "message": "transient bad"},
    )
    oauth = AsyncMock()
    oauth.get_auth_headers = lambda: {"Authorization": "Bearer X"}
    out = await search.search_messages(
        oauth,
        channels=[
            {"id": "GOOD", "name": "good"},
            {"id": "BAD", "name": "bad"},
        ],
        contacts=[],
        query="x",
    )
    assert out["scopes_searched"] == 2
    assert out["scopes_errored"] == 1
    assert out["total_found"] == 1
    assert out["results"][0]["to_channel"] == "GOOD"


@pytest.mark.asyncio
async def test_search_includes_sample_errors_key_even_on_success(httpx_mock):
    """Schema stability: callers can rely on sample_errors being present."""
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
        json={"messages": []},
    )
    oauth = AsyncMock()
    oauth.get_auth_headers = lambda: {"Authorization": "Bearer X"}
    out = await search.search_messages(
        oauth,
        channels=[{"id": "C1", "name": "g"}],
        contacts=[],
        query="x",
    )
    assert "sample_errors" in out
    assert out["sample_errors"] == []
