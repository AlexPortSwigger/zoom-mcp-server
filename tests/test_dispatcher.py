import pytest

from server.dispatcher import build_url, paginate_all
from server import http_client


@pytest.fixture(autouse=True)
async def _reset_client():
    yield
    await http_client.close_client()


def test_build_url_substitutes_path_params():
    url = build_url(
        "https://api.zoom.us/v2",
        "/chat/channels/{channelId}/members",
        path_params={"channelId": "ABC123"},
    )
    assert url == "https://api.zoom.us/v2/chat/channels/ABC123/members"


def test_build_url_with_no_params():
    url = build_url("https://api.zoom.us/v2", "/users/me")
    assert url == "https://api.zoom.us/v2/users/me"


@pytest.mark.asyncio
async def test_paginate_all_chases_next_page_token(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url="https://api.zoom.us/v2/x?page_size=100",
        json={"items": [1, 2], "next_page_token": "tok1"},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.zoom.us/v2/x?page_size=100&next_page_token=tok1",
        json={"items": [3, 4], "next_page_token": ""},
    )
    items = await paginate_all(
        "GET",
        "https://api.zoom.us/v2/x",
        items_key="items",
        headers={"Authorization": "Bearer X"},
    )
    assert items == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_paginate_all_respects_max_items(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url="https://api.zoom.us/v2/x?page_size=100",
        json={"items": [1, 2, 3, 4, 5], "next_page_token": "tok1"},
    )
    items = await paginate_all(
        "GET",
        "https://api.zoom.us/v2/x",
        items_key="items",
        max_items=3,
        headers={"Authorization": "Bearer X"},
    )
    assert items == [1, 2, 3]


def test_endpoints_table_has_25_tools():
    from server.endpoints import ENDPOINTS

    assert len(ENDPOINTS) == 25


def test_endpoints_have_unique_names():
    from server.endpoints import ENDPOINTS

    names = [e["name"] for e in ENDPOINTS]
    assert len(names) == len(set(names))


def test_endpoints_all_have_handler():
    from server.endpoints import ENDPOINTS

    for ep in ENDPOINTS:
        assert "handler" in ep, f"{ep['name']} missing handler"


def test_endpoint_by_name_lookup():
    from server.endpoints import endpoint_by_name

    # AI Companion search
    assert endpoint_by_name("zoom_search_ai")["handler"] == "ai_companion_search"
    # Manual fan-out fallback
    assert endpoint_by_name("zoom_search_messages")["handler"] == "search_messages"


def test_endpoint_by_name_raises_keyerror():
    from server.endpoints import endpoint_by_name

    with pytest.raises(KeyError):
        endpoint_by_name("zoom_unknown")
