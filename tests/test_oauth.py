from datetime import datetime, timedelta

import pytest

from server.oauth import ZoomOAuthHandler
from server.token_store import TokenStore


def test_get_auth_url_contains_required_params(tmp_path):
    store = TokenStore(tmp_path / "tokens.enc", tmp_path / "tokens.key")
    h = ZoomOAuthHandler(
        "CID", "CSEC", token_store=store,
        redirect_uri="http://localhost:8000/cb",
    )
    url = h.get_auth_url()
    assert "client_id=CID" in url
    assert "response_type=code" in url
    assert "redirect_uri=" in url


def test_get_auth_headers_uses_loaded_token(tmp_path):
    store = TokenStore(tmp_path / "tokens.enc", tmp_path / "tokens.key")
    store.save("AT123", "RT", datetime.now() + timedelta(hours=1))
    h = ZoomOAuthHandler("client_id", "client_secret", token_store=store)
    headers = h.get_auth_headers()
    assert headers["Authorization"] == "Bearer AT123"


@pytest.mark.asyncio
async def test_refresh_uses_existing_refresh_token(httpx_mock, tmp_path):
    store = TokenStore(tmp_path / "tokens.enc", tmp_path / "tokens.key")
    store.save("OLD", "REFRESH123", datetime.now() - timedelta(minutes=1))
    httpx_mock.add_response(
        url="https://zoom.us/oauth/token",
        json={
            "access_token": "NEW",
            "refresh_token": "REFRESH456",
            "expires_in": 3600,
            "token_type": "Bearer",
        },
    )
    h = ZoomOAuthHandler("cid", "csec", token_store=store)
    ok = await h.refresh_access_token()
    assert ok is True
    assert store.load()["access_token"] == "NEW"
    assert store.load()["refresh_token"] == "REFRESH456"


@pytest.mark.asyncio
async def test_refresh_returns_false_with_no_refresh_token(tmp_path):
    store = TokenStore(tmp_path / "tokens.enc", tmp_path / "tokens.key")
    h = ZoomOAuthHandler("cid", "csec", token_store=store)
    assert await h.refresh_access_token() is False


@pytest.mark.asyncio
async def test_make_authenticated_request_passes_bearer(httpx_mock, tmp_path):
    store = TokenStore(tmp_path / "tokens.enc", tmp_path / "tokens.key")
    store.save("AT", "RT", datetime.now() + timedelta(hours=1))
    httpx_mock.add_response(
        url="https://api.zoom.us/v2/something",
        json={"ok": True},
        match_headers={"Authorization": "Bearer AT"},
    )
    h = ZoomOAuthHandler("cid", "csec", token_store=store)
    r = await h.make_authenticated_request("GET", "https://api.zoom.us/v2/something")
    assert r.status_code == 200
