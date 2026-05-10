"""Single shared httpx.AsyncClient with TLS 1.2+ and unified retry policy."""
import asyncio
import ssl
from typing import Optional

import httpx

_CLIENT: Optional[httpx.AsyncClient] = None


def _ca_bundle() -> Optional[str]:
    """Return path to a CA bundle, preferring the bundled certifi cacert.pem.

    Python on macOS (and some Linux distributions when launched via certain
    paths) doesn't always have a populated system CA store, which makes
    ssl.create_default_context() fail Zoom TLS handshakes with
    'CERTIFICATE_VERIFY_FAILED'. Pointing at certifi's bundled cacert.pem
    fixes this — and certifi is already a transitive dependency of httpx
    that we ship inside the MCPB.
    """
    try:
        import certifi
        return certifi.where()
    except ImportError:
        return None


def _build_ssl_context() -> ssl.SSLContext:
    ca = _ca_bundle()
    ctx = ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def get_client() -> httpx.AsyncClient:
    global _CLIENT
    if _CLIENT is None or _CLIENT.is_closed:
        _CLIENT = httpx.AsyncClient(
            verify=_build_ssl_context(),
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
            headers={"User-Agent": "zoom-mcp/2.0"},
        )
    return _CLIENT


async def request_with_retry(
    method: str,
    url: str,
    *,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    **kwargs,
) -> httpx.Response:
    """Make an HTTP request with rate-limit and 5xx-aware retries."""
    client = get_client()
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.RequestError as exc:
            last_exc = exc
            if attempt >= max_retries:
                raise
            await asyncio.sleep(retry_delay * (2 ** attempt))
            continue

        if response.status_code == 429:
            if attempt >= max_retries:
                return response
            wait = float(response.headers.get("Retry-After", retry_delay))
            await asyncio.sleep(wait)
            continue

        if 500 <= response.status_code < 600:
            if attempt >= max_retries:
                return response
            await asyncio.sleep(retry_delay * (2 ** attempt))
            continue

        return response

    if last_exc:
        raise last_exc
    raise RuntimeError("retry loop exited unexpectedly")


async def close_client() -> None:
    global _CLIENT
    if _CLIENT is not None:
        try:
            await _CLIENT.aclose()
        except Exception:
            pass
        _CLIENT = None
