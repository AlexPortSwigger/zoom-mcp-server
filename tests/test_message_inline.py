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


@pytest.mark.asyncio
async def test_get_message_failure_raises():
    oauth = AsyncMock()
    oauth.make_authenticated_request = AsyncMock(
        return_value=httpx.Response(404, text="not found")
    )
    with pytest.raises(RuntimeError, match="HTTP 404"):
        await messages.get_message(oauth, message_id="M1", channel_id="C1")
