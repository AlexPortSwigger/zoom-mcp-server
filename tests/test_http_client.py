import ssl

import pytest

from server import http_client
from server.http_client import (
    _build_ssl_context,
    close_client,
    get_client,
    request_with_retry,
)


@pytest.fixture(autouse=True)
async def _reset_client():
    """Ensure each test starts with a fresh client (other tests may have closed it)."""
    yield
    await close_client()


def test_ssl_context_minimum_tls_v1_2():
    ctx = _build_ssl_context()
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2


def test_ssl_context_uses_certifi_ca_bundle():
    """Regression: must use certifi's CA bundle so Zoom TLS handshakes
    don't fail on macOS / non-system Python where the OS CA store isn't
    populated for the running interpreter."""
    import os

    import certifi

    from server.http_client import _ca_bundle

    ca = _ca_bundle()
    assert ca is not None, "certifi must be importable from the bundle"
    assert ca == certifi.where()
    assert os.path.isfile(ca), f"certifi CA bundle missing at {ca}"


def test_ssl_context_loads_real_certs():
    """The built SSL context should have real CA certs loaded — not zero."""
    ctx = _build_ssl_context()
    certs = ctx.get_ca_certs()
    assert len(certs) > 50, (
        f"expected many CA certs from certifi bundle, got {len(certs)}"
    )


def test_client_is_singleton():
    c1 = get_client()
    c2 = get_client()
    assert c1 is c2


@pytest.mark.asyncio
async def test_retry_on_429(httpx_mock):
    httpx_mock.add_response(status_code=429, headers={"Retry-After": "0"}, json={})
    httpx_mock.add_response(status_code=200, json={"ok": True})
    r = await request_with_retry("GET", "https://api.zoom.us/v2/x")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_retry_on_5xx(httpx_mock):
    httpx_mock.add_response(status_code=503, json={})
    httpx_mock.add_response(status_code=200, json={"ok": True})
    r = await request_with_retry("GET", "https://api.zoom.us/v2/x", retry_delay=0)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_no_retry_on_4xx(httpx_mock):
    httpx_mock.add_response(status_code=403, json={"err": "forbidden"})
    r = await request_with_retry("GET", "https://api.zoom.us/v2/x", retry_delay=0)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_max_retries_exhausted_returns_last(httpx_mock):
    for _ in range(4):  # 1 initial + 3 retries
        httpx_mock.add_response(status_code=503, json={})
    r = await request_with_retry(
        "GET", "https://api.zoom.us/v2/x", retry_delay=0, max_retries=3
    )
    assert r.status_code == 503
