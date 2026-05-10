"""Zoom OAuth2 PKCE handler.

Public-client flow — no client_secret. Uses localhost HTTP callback to
auto-capture the authorization code (works with Zoom dev apps where
http://localhost is an allowed redirect URI).
"""
import asyncio
import base64
import hashlib
import logging
import secrets
import shutil
import socket
import subprocess
import threading
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .http_client import request_with_retry
from .token_store import TokenStore

ZOOM_AUTH_URL = "https://zoom.us/oauth/authorize"
ZOOM_TOKEN_URL = "https://zoom.us/oauth/token"

# Ports we'll try in order for the OAuth callback listener. Each must be
# registered as a redirect URI in the Zoom dev app. Currently a single
# port (53682) chosen for low conflict probability — it's in the IANA
# dynamic/private range (49152-65535) and matches what gcloud SDK uses
# for its OAuth callback (proven to rarely conflict on dev machines).
# We migrated away from 8000 in v2.2.7 because 8000 is the default for
# many common dev servers (jupyter, django, http.server) and the
# IPv4/IPv6 dual-stack fix combined with a rare port should make
# fallback ports unnecessary.
DEFAULT_PORTS = (53682,)


def _diagnose_port_holder(port: int) -> str:
    """Best-effort: name + PID of the process holding `port`. Used to make
    'port already in use' errors actionable instead of just saying so."""
    lsof = shutil.which("lsof")
    if not lsof:
        return "(install lsof to identify the process)"
    try:
        out = subprocess.run(
            [lsof, "-nP", "-iTCP:%d" % port, "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=2,
        ).stdout
    except (subprocess.TimeoutExpired, OSError) as e:
        return f"(lsof failed: {e})"
    lines = out.strip().splitlines()
    if len(lines) <= 1:
        return "(no listener — port may be held in TIME_WAIT or by IPv6-only)"
    # Skip header, return first PID and process name
    fields = lines[1].split()
    if len(fields) >= 2:
        return f"PID {fields[1]} ({fields[0]})"
    return out[:200]


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _gen_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) per RFC 7636 (SHA-256)."""
    verifier = _b64url(secrets.token_bytes(64))  # 86 chars
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


class _CallbackState:
    """Shared mutable state across one or more concurrent HTTPServer
    instances (we run one on IPv4 + one on IPv6 for the same OAuth
    flow). Whichever family the browser hits, the result lands here."""
    def __init__(self):
        self.auth_code: Optional[str] = None
        self.auth_state: Optional[str] = None
        self.auth_error: Optional[str] = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        # Server has a `state` attribute (a _CallbackState) attached by
        # the launcher. If for some reason it doesn't, fall back to per-
        # server attributes for backwards compat with old callers.
        state = getattr(self.server, "state", self.server)
        parsed = urlparse(self.path)
        if parsed.path != getattr(self.server, "expected_path", "/oauth/callback"):
            self.send_response(404)
            self.end_headers()
            return
        params = parse_qs(parsed.query)
        if "code" in params:
            state.auth_code = params["code"][0]
            state.auth_state = params.get("state", [""])[0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                "<html><body style='font-family:sans-serif;max-width:600px;"
                "margin:60px auto;padding:0 20px'>"
                "<h2 style='color:#2d8cff'>Authorization successful</h2>"
                "<p>You can close this window and return to Claude.</p>"
                "<p style='color:#888;font-size:13px'>If Claude doesn't "
                "acknowledge in a few seconds, the local listener may "
                "have crashed — check the zoom-mcp logs.</p>"
                "<script>setTimeout(function(){window.close()},2000)</script>"
                "</body></html>".encode("utf-8")
            )
        elif "error" in params:
            state.auth_error = params["error"][0]
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                (
                    "<html><body style='font-family:sans-serif;max-width:"
                    "600px;margin:60px auto;padding:0 20px'>"
                    "<h2 style='color:#c00'>Authorization failed</h2>"
                    f"<p>Zoom returned: <code>{params['error'][0]}</code></p>"
                    "<p>Close this window and re-run "
                    "<code>zoom_auth_login</code> in Claude.</p>"
                    "</body></html>"
                ).encode()
            )
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        pass


class ZoomOAuthHandler:
    """OAuth2 + PKCE flow for Zoom — no client secret."""

    def __init__(
        self,
        client_id: str,
        token_store: TokenStore,
        redirect_uri: str,
        logger: Optional[logging.Logger] = None,
    ):
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.token_store = token_store
        self.logger = logger or logging.getLogger("zoom.oauth")

    # ---------- headers / authenticated requests ----------

    def get_auth_headers(self) -> Dict[str, str]:
        data = self.token_store.load()
        if not data or not data.get("access_token"):
            raise RuntimeError(
                "No access token; call zoom_auth_login first."
            )
        return {
            "Authorization": (
                f"{data.get('token_type', 'Bearer')} {data['access_token']}"
            )
        }

    async def ensure_authenticated(self) -> bool:
        """Refresh the token if expired; never opens a browser here.

        Use run_browser_flow for interactive auth. Other tools call this on
        every request, so it must be quick and non-blocking when there's no
        valid session.
        """
        if not self.token_store.is_expired():
            return True
        data = self.token_store.load()
        if data and data.get("refresh_token"):
            return await self.refresh_access_token()
        return False

    async def maybe_auth_on_startup(self) -> None:
        """Trigger the browser auth flow eagerly if there's no usable session.

        Intended to be fired as a background task at server startup so that
        first-time users see the OAuth window pop up immediately on install,
        rather than only when Claude later calls a tool that needs auth.

        Skips silently when:
          - A valid (non-expired) token already exists.
          - A refresh token exists (refresh happens lazily on the first
            authenticated request).

        Failures (port conflict, user closes window, timeout) are logged but
        never crash the server — the user can still run zoom_auth_login
        manually afterwards.
        """
        data = self.token_store.load()
        if data and data.get("refresh_token"):
            return
        if not self.token_store.is_expired():
            return
        self.logger.info(
            "No Zoom session on startup; launching browser auth flow"
        )
        try:
            ok = await self.run_browser_flow()
            if not ok:
                self.logger.warning(
                    "Startup auth flow did not complete; user can run "
                    "zoom_auth_login manually."
                )
        except Exception as e:
            self.logger.error("Startup auth flow error: %s", e)

    async def refresh_access_token(self) -> bool:
        data = self.token_store.load()
        if not data or not data.get("refresh_token"):
            return False
        try:
            r = await request_with_retry(
                "POST",
                ZOOM_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": data["refresh_token"],
                    "client_id": self.client_id,
                },
            )
        except Exception as e:
            self.logger.error("Token refresh failed: %s", e)
            return False
        if r.status_code != 200:
            self.logger.error("Token refresh HTTP %d", r.status_code)
            return False
        return self._save_token_response(
            r.json(), existing_refresh=data["refresh_token"]
        )

    async def make_authenticated_request(
        self, method: str, url: str, **kwargs
    ) -> httpx.Response:
        if not await self.ensure_authenticated():
            raise RuntimeError(
                "Not authenticated. Use zoom_auth_login to start the flow."
            )
        headers = kwargs.get("headers", {})
        headers.update(self.get_auth_headers())
        kwargs["headers"] = headers
        response = await request_with_retry(method, url, **kwargs)
        if response.status_code == 401 and await self.refresh_access_token():
            headers.update(self.get_auth_headers())
            kwargs["headers"] = headers
            response = await request_with_retry(method, url, **kwargs)
        return response

    # ---------- browser flow ----------

    def get_auth_url(
        self,
        code_challenge: str,
        state: str,
        redirect_uri: Optional[str] = None,
    ) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri or self.redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        return f"{ZOOM_AUTH_URL}?{urlencode(params)}"

    def _candidate_ports(self) -> List[int]:
        """Return the port from redirect_uri first, then any fallbacks
        not equal to it. Each returned port must already be registered
        in the Zoom dev app for OAuth to actually accept the callback;
        we just try them in order until one's free."""
        primary = urlparse(self.redirect_uri).port or DEFAULT_PORTS[0]
        ports = [primary]
        for p in DEFAULT_PORTS:
            if p != primary:
                ports.append(p)
        return ports

    def _bind_callback_listeners(
        self, port: int
    ) -> Tuple[List[HTTPServer], "_CallbackState"]:
        """Bind HTTPServer instances on BOTH 127.0.0.1 and ::1 for `port`,
        sharing one state object. Returns (servers, state).

        Why dual-stack: macOS resolves `localhost` to BOTH 127.0.0.1 and
        ::1, and the browser may pick either when following Zoom's
        redirect. If we only listen on one, the other gets connection
        refused and (depending on browser) the callback silently fails.
        Listening on both eliminates the IPv4/IPv6 race entirely.

        Raises OSError if neither family could bind to `port`."""
        state = _CallbackState()
        servers: List[HTTPServer] = []
        errors: List[str] = []
        for family, addr in [
            (socket.AF_INET, "127.0.0.1"),
            (socket.AF_INET6, "::1"),
        ]:
            try:
                cls = type(
                    "_BoundHTTPServer",
                    (HTTPServer,),
                    {"address_family": family},
                )
                srv = cls((addr, port), _CallbackHandler)
                # Share the same state across both listeners
                srv.state = state
                servers.append(srv)
                self.logger.info(
                    "OAuth callback listening on %s:%d (family=%s)",
                    addr, port,
                    "IPv4" if family == socket.AF_INET else "IPv6",
                )
            except OSError as e:
                errors.append(f"{addr}:{port} -> {e}")
        if not servers:
            raise OSError(
                "Could not bind callback listener on either IPv4 or IPv6 "
                "loopback. Errors: " + "; ".join(errors)
            )
        return servers, state

    async def run_browser_flow(self, timeout_seconds: int = 300) -> bool:
        """Open a browser, capture the OAuth callback on localhost, exchange
        the code + PKCE verifier for tokens. Returns True on success.

        Robustness improvements over the original:
        - Dual-stack listener (IPv4 127.0.0.1 + IPv6 ::1) — fixes the
          most common cause of "callback didn't work": browser picks a
          different family than Python's HTTPServer bound on.
        - Falls back through a list of candidate ports (registered in
          the Zoom dev app) if the primary one is in use.
        - Logs the PID + name of the process holding a busy port so
          the user can fix the conflict instead of just being told.
        - Logs the auth URL so the user can paste it into a browser
          manually if `webbrowser.open` silently fails (sandboxed
          environments)."""
        callback_path = (
            urlparse(self.redirect_uri).path or "/oauth/callback"
        )
        primary_port = (
            urlparse(self.redirect_uri).port or DEFAULT_PORTS[0]
        )

        # Try each candidate port until one binds on (at least one of)
        # IPv4 or IPv6 loopback.
        servers: List[HTTPServer] = []
        state: Optional[_CallbackState] = None
        bound_port: Optional[int] = None
        for port in self._candidate_ports():
            try:
                servers, state = self._bind_callback_listeners(port)
                bound_port = port
                break
            except OSError as e:
                holder = _diagnose_port_holder(port)
                self.logger.warning(
                    "OAuth port %d unavailable (%s); held by %s",
                    port, e, holder,
                )

        if not servers or state is None or bound_port is None:
            self.logger.error(
                "All candidate OAuth ports busy: %s. Free one (e.g. "
                "`kill <pid>`) or set ZOOM_REDIRECT_URI env var to a "
                "URL with a free port that's also registered in the "
                "Zoom dev app.",
                self._candidate_ports(),
            )
            return False

        # If we bound to a non-primary fallback port, the redirect URI
        # we hand to Zoom must match THAT port — otherwise Zoom will
        # reject the auth request as a redirect_uri mismatch.
        effective_redirect_uri = self.redirect_uri
        if bound_port != primary_port:
            parsed = urlparse(self.redirect_uri)
            effective_redirect_uri = (
                f"{parsed.scheme}://{parsed.hostname}:{bound_port}"
                f"{callback_path}"
            )
            self.logger.warning(
                "Primary port %d was busy; falling back to %d. The Zoom "
                "dev app MUST have %s registered as an allowed redirect "
                "URI or this will fail with 'redirect_uri mismatch'.",
                primary_port, bound_port, effective_redirect_uri,
            )

        for srv in servers:
            srv.expected_path = callback_path

        verifier, challenge = _gen_pkce_pair()
        csrf_state = _b64url(secrets.token_bytes(16))

        # Set expected path on each server too (handler reads from server)
        def serve(srv):
            while state.auth_code is None and state.auth_error is None:
                srv.handle_request()

        for srv in servers:
            threading.Thread(target=serve, args=(srv,), daemon=True).start()

        url = self.get_auth_url(
            challenge, csrf_state, redirect_uri=effective_redirect_uri,
        )
        self.logger.info(
            "Opening Zoom OAuth in browser. If no browser pops up, "
            "paste this URL manually: %s", url,
        )
        try:
            opened = webbrowser.open(url)
            if not opened:
                self.logger.warning(
                    "webbrowser.open returned False — browser may not "
                    "have launched. Paste the URL above manually.",
                )
        except Exception as e:
            self.logger.warning(
                "webbrowser.open raised %s. Paste the URL above manually.",
                e,
            )

        loop_start = asyncio.get_event_loop().time()
        while state.auth_code is None and state.auth_error is None:
            await asyncio.sleep(0.1)
            if (
                asyncio.get_event_loop().time() - loop_start
                > timeout_seconds
            ):
                self.logger.error(
                    "OAuth callback timeout after %ds. Browser may "
                    "have failed to reach %s — check macOS firewall "
                    "isn't blocking incoming connections to Python, "
                    "or open the URL above manually.",
                    timeout_seconds, effective_redirect_uri,
                )
                for srv in servers:
                    srv.server_close()
                return False
        for srv in servers:
            srv.server_close()

        if state.auth_error:
            self.logger.error("OAuth flow returned error: %s", state.auth_error)
            return False
        if not state.auth_code:
            return False
        if state.auth_state != csrf_state:
            self.logger.error(
                "OAuth state mismatch (CSRF protection) — expected %r, "
                "got %r. Reauthing.", csrf_state, state.auth_state,
            )
            return False
        # Hand the same effective redirect URI to the token-exchange
        # call, since Zoom validates it must match the authorize step.
        return await self._exchange_code(
            state.auth_code, verifier, redirect_uri=effective_redirect_uri,
        )

    async def _exchange_code(
        self,
        code: str,
        verifier: str,
        redirect_uri: Optional[str] = None,
    ) -> bool:
        try:
            r = await request_with_retry(
                "POST",
                ZOOM_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri or self.redirect_uri,
                    "client_id": self.client_id,
                    "code_verifier": verifier,
                },
            )
        except Exception as e:
            self.logger.error("Code exchange failed: %s", e)
            return False
        if r.status_code != 200:
            self.logger.error(
                "Code exchange HTTP %d: %s", r.status_code, r.text
            )
            return False
        return self._save_token_response(r.json())

    def _save_token_response(
        self, payload: dict, existing_refresh: Optional[str] = None
    ) -> bool:
        access = payload.get("access_token")
        if not access:
            return False
        refresh = payload.get("refresh_token", existing_refresh)
        expires_in = int(payload.get("expires_in", 3600))
        self.token_store.save(
            access_token=access,
            refresh_token=refresh,
            expires_at=datetime.now() + timedelta(seconds=expires_in),
            token_type=payload.get("token_type", "Bearer"),
            scope=payload.get("scope"),
        )
        return True
