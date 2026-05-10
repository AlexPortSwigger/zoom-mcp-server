from unittest.mock import AsyncMock

import httpx
import pytest

from server import http_client, shared_spaces


@pytest.fixture(autouse=True)
async def _reset_client():
    yield
    await http_client.close_client()


@pytest.mark.asyncio
async def test_list_shared_spaces(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url="https://api.zoom.us/v2/chat/spaces?page_size=100",
        json={"spaces": [{"id": "S1", "name": "Eng"}], "next_page_token": ""},
    )
    oauth = AsyncMock()
    oauth.get_auth_headers = lambda: {"Authorization": "Bearer X"}
    out = await shared_spaces.list_shared_spaces(oauth)
    assert out[0]["id"] == "S1"


@pytest.mark.asyncio
async def test_get_shared_space_detail_only(httpx_mock):
    oauth = AsyncMock()
    oauth.get_auth_headers = lambda: {"Authorization": "Bearer X"}
    oauth.make_authenticated_request = AsyncMock(
        return_value=httpx.Response(200, json={"id": "S1", "name": "Eng"})
    )
    out = await shared_spaces.get_shared_space(oauth, "S1", include="detail")
    assert out["detail"]["id"] == "S1"
    assert "channels" not in out
    assert "members" not in out


@pytest.mark.asyncio
async def test_get_shared_space_all(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url="https://api.zoom.us/v2/chat/spaces/S1/channels?page_size=100",
        json={"channels": [{"id": "c1"}], "next_page_token": ""},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.zoom.us/v2/chat/spaces/S1/members?page_size=100",
        json={"members": [{"id": "u1"}], "next_page_token": ""},
    )
    oauth = AsyncMock()
    oauth.get_auth_headers = lambda: {"Authorization": "Bearer X"}
    oauth.make_authenticated_request = AsyncMock(
        return_value=httpx.Response(200, json={"id": "S1", "name": "Eng"})
    )
    out = await shared_spaces.get_shared_space(oauth, "S1", include="all")
    assert out["detail"]["id"] == "S1"
    assert out["channels"][0]["id"] == "c1"
    assert out["members"][0]["id"] == "u1"
