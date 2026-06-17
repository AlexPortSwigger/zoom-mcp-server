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


@pytest.mark.asyncio
async def test_search_messages_returns_fallback_hint_on_zero_hits(httpx_mock):
    """When search_messages returns 0 hits and 0 errors, it must include
    a hint pointing the caller (Claude) at zoom_search_history. This is
    the auto-fallback signal that makes deep search discoverable when
    the 24h cap silently hides older matches."""
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(
            "https://api.zoom.us/v2/chat/users/me/messages",
            params={
                "search_type": "message",
                "search_key": "SVPG",
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
        query="SVPG",
    )
    assert out["total_found"] == 0
    assert out["scopes_errored"] == 0
    assert "hint" in out
    assert "zoom_search_history" in out["hint"]
    assert "24" in out["hint"]  # mentions the 24h cap


@pytest.mark.asyncio
async def test_search_messages_no_hint_when_hits_found(httpx_mock):
    """No hint needed when results came back."""
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
        json={"messages": [
            {"id": "m1", "message": "hi", "date_time": "2026-05-10T10:00:00Z"}
        ]},
    )
    oauth = AsyncMock()
    oauth.get_auth_headers = lambda: {"Authorization": "Bearer X"}
    out = await search.search_messages(
        oauth, channels=[{"id": "C1", "name": "g"}], contacts=[], query="x",
    )
    assert out["total_found"] == 1
    assert "hint" not in out


# ----------------------------------------------------------------------
# search_history — deep client-side keyword search (no 24h cap)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_history_filters_messages_by_substring(httpx_mock):
    """search_history reads channel history (browse mode) and applies the
    keyword filter client-side. This is what makes it bypass Zoom's 24h
    keyword-search cap."""
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(
            "https://api.zoom.us/v2/chat/users/me/messages",
            params={"to_channel": "C1", "from": "2026-04-01T00:00:00Z",
                    "to": "2026-05-01T23:59:59Z", "page_size": 50},
        ),
        json={
            "messages": [
                {"id": "m1", "message": "We should read SVPG by Cagan",
                 "sender": "alex@x", "date_time": "2026-04-15T10:00:00Z"},
                {"id": "m2", "message": "Lunch tomorrow?",
                 "sender": "bob@x", "date_time": "2026-04-15T11:00:00Z"},
                {"id": "m3", "message": "Cagan's Empowered is great",
                 "sender": "alex@x", "date_time": "2026-04-16T09:00:00Z"},
            ],
            "next_page_token": "",
        },
    )
    oauth = AsyncMock()
    oauth.get_auth_headers = lambda: {"Authorization": "Bearer X"}
    out = await search.search_history(
        oauth,
        channels=[{"id": "C1", "name": "Devs"}],
        contacts=[],
        query="Cagan",
        from_date="2026-04-01",
        to_date="2026-05-01",
    )
    assert out["mode"] == "history"
    assert out["total_found"] == 2  # SVPG msg + Empowered msg
    assert out["scopes_searched"] == 1
    assert out["scopes_errored"] == 0
    # Sorted recent-first, tagged with channel
    assert out["results"][0]["id"] == "m3"
    assert out["results"][0]["channel_name"] == "Devs"
    assert out["results"][0]["to_channel"] == "C1"


@pytest.mark.asyncio
async def test_search_history_sender_filter(httpx_mock):
    """sender_filter narrows results to messages from a specific sender.
    Used for 'find messages from <person> about <topic>'."""
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(
            "https://api.zoom.us/v2/chat/users/me/messages",
            params={"to_channel": "C1", "from": "2026-04-01T00:00:00Z", "page_size": 50},
        ),
        json={
            "messages": [
                {"id": "m1", "message": "podcast rec: Lenny",
                 "sender": "alex.craig@portswigger.net",
                 "date_time": "2026-04-15T10:00:00Z"},
                {"id": "m2", "message": "I love that podcast too",
                 "sender": "tom@portswigger.net",
                 "date_time": "2026-04-15T11:00:00Z"},
            ],
        },
    )
    oauth = AsyncMock()
    oauth.get_auth_headers = lambda: {"Authorization": "Bearer X"}
    out = await search.search_history(
        oauth,
        channels=[{"id": "C1", "name": "Devs"}],
        contacts=[],
        query="podcast",
        from_date="2026-04-01",
        sender_filter="alex.craig",
    )
    assert out["total_found"] == 1
    assert out["results"][0]["id"] == "m1"


@pytest.mark.asyncio
async def test_search_history_sender_filter_matches_display_name(httpx_mock):
    """sender_filter checks both sender (email) and sender_display_name."""
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(
            "https://api.zoom.us/v2/chat/users/me/messages",
            params={"to_channel": "C1", "from": "2026-04-01T00:00:00Z", "page_size": 50},
        ),
        json={
            "messages": [
                {"id": "m1", "message": "interesting article",
                 "sender": "ac@portswigger.net",
                 "sender_display_name": "Alex Craig",
                 "date_time": "2026-04-15T10:00:00Z"},
            ],
        },
    )
    oauth = AsyncMock()
    oauth.get_auth_headers = lambda: {"Authorization": "Bearer X"}
    out = await search.search_history(
        oauth,
        channels=[{"id": "C1", "name": "Devs"}],
        contacts=[],
        query="article",
        from_date="2026-04-01",
        sender_filter="Alex Craig",  # matches display name
    )
    assert out["total_found"] == 1


@pytest.mark.asyncio
async def test_search_history_aggregates_across_scopes(httpx_mock):
    """Each channel + contact contributes to the merged result set,
    sorted by date_time DESC."""
    for ch in ("C1", "C2"):
        httpx_mock.add_response(
            method="GET",
            url=httpx.URL(
                "https://api.zoom.us/v2/chat/users/me/messages",
                params={"to_channel": ch, "from": "2026-04-01T00:00:00Z", "page_size": 50},
            ),
            json={
                "messages": [
                    {"id": f"{ch}-1", "message": "TARGET word here",
                     "sender": "x@y", "date_time": f"2026-05-0{1 if ch=='C1' else 2}T10:00:00Z"},
                ],
            },
        )
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(
            "https://api.zoom.us/v2/chat/users/me/messages",
            params={"to_contact": "U1", "from": "2026-04-01T00:00:00Z", "page_size": 50},
        ),
        json={
            "messages": [
                {"id": "U1-1", "message": "TARGET in DM",
                 "sender": "x@y", "date_time": "2026-05-03T10:00:00Z"},
            ],
        },
    )
    oauth = AsyncMock()
    oauth.get_auth_headers = lambda: {"Authorization": "Bearer X"}
    out = await search.search_history(
        oauth,
        channels=[{"id": "C1", "name": "ch1"}, {"id": "C2", "name": "ch2"}],
        contacts=[{"id": "U1", "email": "u@y"}],
        query="TARGET",
        from_date="2026-04-01",
    )
    assert out["scopes_searched"] == 3
    assert out["total_found"] == 3
    # Sorted DESC by date_time — DM (May 3) first, then C2 (May 2), then C1 (May 1)
    assert [r["id"] for r in out["results"]] == ["U1-1", "C2-1", "C1-1"]


@pytest.mark.asyncio
async def test_search_history_rejects_empty_query():
    oauth = AsyncMock()
    with pytest.raises(ValueError):
        await search.search_history(
            oauth, channels=[], contacts=[], query="",
            from_date="2026-04-01",
        )


@pytest.mark.asyncio
async def test_search_history_returns_mode_history():
    """Result schema has mode='history' so callers can distinguish
    from search_messages results (mode='fast')."""
    oauth = AsyncMock()
    oauth.get_auth_headers = lambda: {"Authorization": "Bearer X"}
    out = await search.search_history(
        oauth, channels=[], contacts=[], query="x",
        from_date="2026-04-01",
    )
    assert out["mode"] == "history"
    assert out["scopes_searched"] == 0
    assert out["total_found"] == 0
