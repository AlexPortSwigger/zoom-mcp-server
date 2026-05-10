"""Tests for the PKCE-based ZoomOAuthHandler (no client_secret)."""
import base64
import hashlib
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from server import http_client
from server.oauth import ZoomOAuthHandler, _gen_pkce_pair
from server.token_store import TokenStore


@pytest.fixture(autouse=True)
async def _reset_client():
    yield
    await http_client.close_client()


@pytest.fixture
def store(tmp_path):
    return TokenStore(tmp_path / "tokens.enc", tmp_path / "tokens.key")


@pytest.fixture
def oauth(store):
    return ZoomOAuthHandler(
        client_id="CID",
        token_store=store,
        redirect_uri="http://localhost:8000/oauth/callback",
    )


# ---------- PKCE primitives ----------


def test_gen_pkce_pair_produces_valid_pair():
    verifier, challenge = _gen_pkce_pair()
    assert 43 <= len(verifier) <= 128
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert challenge == expected


def test_gen_pkce_pair_is_random():
    a, _ = _gen_pkce_pair()
    b, _ = _gen_pkce_pair()
    assert a != b


# ---------- auth URL ----------


def test_get_auth_url_includes_pkce_params(oauth):
    url = oauth.get_auth_url("CHALLENGE", "STATE")
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    assert qs["response_type"] == ["code"]
    assert qs["client_id"] == ["CID"]
    assert qs["redirect_uri"] == ["http://localhost:8000/oauth/callback"]
    assert qs["code_challenge"] == ["CHALLENGE"]
    assert qs["code_challenge_method"] == ["S256"]
    assert qs["state"] == ["STATE"]


# ---------- token refresh (PKCE — no secret) ----------


@pytest.mark.asyncio
async def test_refresh_uses_client_id_only(httpx_mock, oauth, store):
    store.save("OLD", "REFRESH123", datetime.now() - timedelta(minutes=1))
    captured = {}

    def _capture(request):
        body = request.read().decode()
        for kv in body.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                captured[k] = v
        import httpx
        return httpx.Response(
            200,
            json={
                "access_token": "NEW",
                "refresh_token": "REFRESH456",
                "expires_in": 3600,
            },
        )

    httpx_mock.add_callback(_capture, url="https://zoom.us/oauth/token")
    ok = await oauth.refresh_access_token()
    assert ok is True
    assert "client_secret" not in captured
    assert captured["client_id"] == "CID"
    assert captured["grant_type"] == "refresh_token"


@pytest.mark.asyncio
async def test_refresh_returns_false_with_no_refresh_token(oauth):
    assert await oauth.refresh_access_token() is False


# ---------- code exchange (PKCE — uses code_verifier, not secret) ----------


@pytest.mark.asyncio
async def test_exchange_code_sends_verifier_not_secret(httpx_mock, oauth, store):
    captured = {}

    def _capture(request):
        body = request.read().decode()
        for kv in body.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                captured[k] = v
        import httpx
        return httpx.Response(
            200,
            json={
                "access_token": "AT",
                "refresh_token": "RT",
                "expires_in": 3600,
            },
        )

    httpx_mock.add_callback(_capture, url="https://zoom.us/oauth/token")
    ok = await oauth._exchange_code("auth_code_xyz", "verifier_abc")
    assert ok is True
    assert "client_secret" not in captured
    assert captured["code_verifier"] == "verifier_abc"
    assert captured["client_id"] == "CID"
    assert captured["grant_type"] == "authorization_code"
    assert store.load()["access_token"] == "AT"


# ---------- ensure_authenticated ----------


@pytest.mark.asyncio
async def test_ensure_authenticated_returns_true_for_fresh_token(oauth, store):
    store.save("AT", "RT", datetime.now() + timedelta(hours=1))
    assert await oauth.ensure_authenticated() is True


@pytest.mark.asyncio
async def test_ensure_authenticated_never_blocks_when_no_tokens(oauth):
    """Regression: must not start a browser flow from ensure_authenticated."""
    import asyncio

    result = await asyncio.wait_for(oauth.ensure_authenticated(), timeout=1.0)
    assert result is False


# ---------- headers / authenticated request ----------


def test_get_auth_headers_uses_loaded_token(oauth, store):
    store.save("AT123", "RT", datetime.now() + timedelta(hours=1))
    h = oauth.get_auth_headers()
    assert h["Authorization"] == "Bearer AT123"


def test_get_auth_headers_raises_without_token(oauth):
    with pytest.raises(RuntimeError, match="No access token"):
        oauth.get_auth_headers()


@pytest.mark.asyncio
async def test_make_authenticated_request_passes_bearer(
    httpx_mock, oauth, store
):
    store.save("AT", "RT", datetime.now() + timedelta(hours=1))
    httpx_mock.add_response(
        url="https://api.zoom.us/v2/something",
        json={"ok": True},
        match_headers={"Authorization": "Bearer AT"},
    )
    r = await oauth.make_authenticated_request(
        "GET", "https://api.zoom.us/v2/something"
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_make_authenticated_request_raises_when_no_session(oauth):
    with pytest.raises(RuntimeError, match="zoom_auth_login"):
        await oauth.make_authenticated_request(
            "GET", "https://api.zoom.us/v2/something"
        )


# ---------- maybe_auth_on_startup ----------


@pytest.mark.asyncio
async def test_maybe_auth_skips_when_token_valid(oauth, store):
    """If there's a non-expired token, skip — don't open browser."""
    store.save("AT", "RT", datetime.now() + timedelta(hours=1))
    called = {"browser": False}

    async def _fake_browser_flow(*a, **kw):
        called["browser"] = True
        return True

    oauth.run_browser_flow = _fake_browser_flow
    await oauth.maybe_auth_on_startup()
    assert called["browser"] is False


@pytest.mark.asyncio
async def test_maybe_auth_skips_when_refresh_token_exists(oauth, store):
    """Refresh token exists → defer to lazy refresh; don't open browser."""
    store.save("OLD", "REFRESH", datetime.now() - timedelta(minutes=10))
    called = {"browser": False}

    async def _fake_browser_flow(*a, **kw):
        called["browser"] = True
        return True

    oauth.run_browser_flow = _fake_browser_flow
    await oauth.maybe_auth_on_startup()
    assert called["browser"] is False


@pytest.mark.asyncio
async def test_maybe_auth_runs_browser_when_no_session(oauth):
    """No tokens at all → browser flow fires."""
    called = {"browser": False}

    async def _fake_browser_flow(*a, **kw):
        called["browser"] = True
        return True

    oauth.run_browser_flow = _fake_browser_flow
    await oauth.maybe_auth_on_startup()
    assert called["browser"] is True


@pytest.mark.asyncio
async def test_maybe_auth_swallows_browser_failure(oauth):
    """Browser flow failure must not crash server startup."""

    async def _failing_browser_flow(*a, **kw):
        raise RuntimeError("port in use")

    oauth.run_browser_flow = _failing_browser_flow
    # Must not raise
    await oauth.maybe_auth_on_startup()
