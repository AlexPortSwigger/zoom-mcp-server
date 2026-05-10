import httpx
import pytest

from server.dispatcher import build_url, format_zoom_error, paginate_all
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


def test_format_zoom_error_4711_extracts_scope_and_action():
    body = (
        '{"code":4711,"message":"Invalid access token, does not contain '
        'scopes:[meeting:read:list_meetings, '
        'meeting:read:list_meetings:admin]."}'
    )
    msg = format_zoom_error(400, body)
    assert "code 4711" in msg
    assert "missing scope" in msg.lower()
    assert "meeting:read:list_meetings" in msg
    assert "meeting:read:list_meetings:admin" in msg
    # Tells the user what to do
    assert "re-authenticate" in msg.lower() or "marketplace" in msg.lower()


def test_format_zoom_error_2300_marks_missing_endpoint():
    body = '{"code":2300,"message":"This API endpoint is not recognized."}'
    msg = format_zoom_error(404, body)
    assert "code 2300" in msg
    assert "not exposed" in msg.lower() or "not recognized" in msg.lower()


def test_format_zoom_error_unknown_code_includes_message():
    body = '{"code":300,"message":"Whatever"}'
    msg = format_zoom_error(400, body)
    assert "300" in msg
    assert "Whatever" in msg


def test_format_zoom_error_non_json_body_just_returns_truncated():
    body = "<html>some upstream gateway thing</html>"
    msg = format_zoom_error(502, body)
    assert "502" in msg
    assert "gateway thing" in msg


def test_format_zoom_error_empty_body():
    msg = format_zoom_error(400, "")
    assert "400" in msg


@pytest.mark.asyncio
async def test_paginate_all_surfaces_zoom_error_body(httpx_mock):
    # Simulates the deployed connector's "every channel returns 400"
    # situation: paginate_all must include the Zoom error body in the
    # raised exception so the caller can diagnose. Pre-fix, this raised
    # `Client error '400 Bad Request' for url ...` with no body.
    httpx_mock.add_response(
        method="GET",
        url="https://api.zoom.us/v2/meetings/meeting_summaries?page_size=100",
        status_code=400,
        json={
            "code": 4711,
            "message": (
                "Invalid access token, does not contain "
                "scopes:[meeting:read:list_summaries:admin]."
            ),
        },
    )
    with pytest.raises(httpx.HTTPStatusError) as ei:
        await paginate_all(
            "GET",
            "https://api.zoom.us/v2/meetings/meeting_summaries",
            items_key="summaries",
            headers={"Authorization": "Bearer X"},
        )
    text = str(ei.value)
    # Status code visible
    assert "400" in text
    # Zoom error code visible
    assert "4711" in text
    # Required scope visible
    assert "meeting:read:list_summaries:admin" in text
    # Tells the user what to do
    assert "re-authenticate" in text.lower() or "marketplace" in text.lower()


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
