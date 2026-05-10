"""Tests for the PKCE-based ZoomOAuthHandler (no client_secret)."""
import base64
import hashlib
import socket
from datetime import datetime, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from server import http_client
from server.oauth import (
    DEFAULT_PORTS,
    ZoomOAuthHandler,
    _CallbackState,
    _diagnose_port_holder,
    _gen_pkce_pair,
)
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
        redirect_uri="http://localhost:53682/oauth/callback",
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


# ---------- callback listener ----------


def test_candidate_ports_starts_with_redirect_uri_port(store):
    h = ZoomOAuthHandler(
        client_id="C",
        token_store=store,
        redirect_uri="http://localhost:9999/oauth/callback",
    )
    ports = h._candidate_ports()
    assert ports[0] == 9999, "primary port from redirect_uri must come first"
    # All defaults should appear (no duplicates of primary)
    for p in DEFAULT_PORTS:
        assert p in ports
    assert ports.count(9999) == 1


def test_candidate_ports_uses_default_when_redirect_has_no_port(store):
    h = ZoomOAuthHandler(
        client_id="C",
        token_store=store,
        redirect_uri="http://localhost/oauth/callback",
    )
    assert h._candidate_ports()[0] == DEFAULT_PORTS[0]


def test_default_port_is_53682():
    """v2.2.7: migrated default from 8000 to 53682 (gcloud SDK port,
    IANA dynamic range, low conflict probability)."""
    assert DEFAULT_PORTS[0] == 53682


def _free_port() -> int:
    """Grab a free port for tests."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_bind_callback_listeners_binds_dual_stack(oauth):
    """The fix: oauth flow must bind on BOTH 127.0.0.1 and ::1 so the
    browser's choice of localhost address family doesn't matter."""
    port = _free_port()
    servers, state = oauth._bind_callback_listeners(port)
    try:
        assert isinstance(state, _CallbackState)
        # Should have at least one (IPv4 always available; IPv6 may not be
        # depending on test runner). We require IPv4 at minimum.
        families = {s.address_family for s in servers}
        assert socket.AF_INET in families, "IPv4 binding is the floor"
        # State is shared across all listeners
        for srv in servers:
            assert srv.state is state
    finally:
        for srv in servers:
            srv.server_close()


def test_bind_callback_listeners_raises_when_port_busy(oauth):
    """If port is already taken on both families, the bind helper raises
    OSError so the caller can fall back to a different port."""
    # Hold the port on both 127.0.0.1 and ::1
    holders = []
    port = _free_port()
    for family, addr in [(socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")]:
        try:
            s = socket.socket(family, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            s.bind((addr, port))
            s.listen(1)
            holders.append(s)
        except OSError:
            pass  # IPv6 may not be available in test env
    try:
        if not holders:
            pytest.skip("could not bind port for test setup")
        with pytest.raises(OSError):
            oauth._bind_callback_listeners(port)
    finally:
        for h in holders:
            h.close()


def test_diagnose_port_holder_returns_a_string():
    """We don't care what the lsof output is — just that the helper
    doesn't crash on a likely-free or likely-busy port. It should return
    a string the user can act on (or a clear "no listener" note)."""
    out = _diagnose_port_holder(_free_port())
    assert isinstance(out, str)
    assert len(out) > 0


def test_callback_state_starts_blank():
    s = _CallbackState()
    assert s.auth_code is None
    assert s.auth_state is None
    assert s.auth_error is None


# ---------- auth URL ----------


def test_get_auth_url_includes_pkce_params(oauth):
    url = oauth.get_auth_url("CHALLENGE", "STATE")
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    assert qs["response_type"] == ["code"]
    assert qs["client_id"] == ["CID"]
    assert qs["redirect_uri"] == ["http://localhost:53682/oauth/callback"]
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
