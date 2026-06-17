from unittest.mock import AsyncMock

import httpx
import pytest

from server import http_client, messages


@pytest.fixture(autouse=True)
async def _reset_client():
    yield
    await http_client.close_client()


@pytest.mark.asyncio
async def test_get_message_passes_through_reactions_and_files():
    oauth = AsyncMock()
    oauth.make_authenticated_request = AsyncMock(
        return_value=httpx.Response(
            200,
            json={
                "id": "M1",
                "message": "hello",
                "reactions": [{"emoji": "👍", "count": 3}],
                "files": [
                    {"file_id": "F1", "file_name": "x.txt", "file_size": 10}
                ],
            },
        )
    )
    out = await messages.get_message(oauth, message_id="M1", channel_id="C1")
    assert out["reactions"][0]["emoji"] == "👍"
    assert out["files"][0]["file_id"] == "F1"


@pytest.mark.asyncio
async def test_get_channel_history_requires_scope():
    oauth = AsyncMock()
    with pytest.raises(ValueError):
        await messages.get_channel_history(oauth)


@pytest.mark.asyncio
async def test_get_channel_history_paginates(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url="https://api.zoom.us/v2/chat/users/me/messages?page_size=50&to_channel=C1",
        json={
            "messages": [{"id": "m1", "message": "hi"}],
            "next_page_token": "tok",
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://api.zoom.us/v2/chat/users/me/messages?page_size=50&to_channel=C1"
            "&next_page_token=tok"
        ),
        json={"messages": [{"id": "m2", "message": "yo"}], "next_page_token": ""},
    )
    oauth = AsyncMock()
    oauth.get_auth_headers = lambda: {"Authorization": "Bearer X"}
    out = await messages.get_channel_history(oauth, channel_id="C1")
    assert len(out) == 2
    assert {m["id"] for m in out} == {"m1", "m2"}


def test_to_zoom_ts_widens_bare_dates():
    # bare date -> start / end of day
    assert messages.to_zoom_ts("2026-05-11") == "2026-05-11T00:00:00Z"
    assert messages.to_zoom_ts("2026-05-11", end_of_day=True) == "2026-05-11T23:59:59Z"
    # already a datetime -> untouched
    assert messages.to_zoom_ts("2026-05-11T09:30:00Z") == "2026-05-11T09:30:00Z"
    # empty / None -> None
    assert messages.to_zoom_ts(None) is None
    assert messages.to_zoom_ts("") is None


@pytest.mark.asyncio
async def test_get_channel_history_sends_iso_dates(httpx_mock):
    # Zoom ignores bare yyyy-MM-dd; the connector must send ISO-8601 with Z.
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(
            "https://api.zoom.us/v2/chat/users/me/messages",
            params={
                "page_size": 50,
                "to_channel": "C1",
                "from": "2026-05-01T00:00:00Z",
                "to": "2026-05-31T23:59:59Z",
            },
        ),
        json={"messages": [{"id": "m1", "message": "hi"}]},
    )
    oauth = AsyncMock()
    oauth.get_auth_headers = lambda: {"Authorization": "Bearer X"}
    out = await messages.get_channel_history(
        oauth, channel_id="C1", from_date="2026-05-01", to_date="2026-05-31"
    )
    assert len(out) == 1
    req = httpx_mock.get_requests()[0]
    assert req.url.params["from"] == "2026-05-01T00:00:00Z"
    assert req.url.params["to"] == "2026-05-31T23:59:59Z"


@pytest.mark.asyncio
async def test_get_message_failure_raises():
    oauth = AsyncMock()
    oauth.make_authenticated_request = AsyncMock(
        return_value=httpx.Response(404, text="not found")
    )
    with pytest.raises(RuntimeError, match="HTTP 404"):
        await messages.get_message(oauth, message_id="M1", channel_id="C1")
