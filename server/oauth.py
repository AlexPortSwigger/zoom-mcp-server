"""Zoom OAuth2 authorization-code handler with browser callback flow."""
import asyncio
import logging
import socket
import threading
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .http_client import request_with_retry
from .token_store import TokenStore

ZOOM_AUTH_URL = "https://zoom.us/oauth/authorize"
ZOOM_TOKEN_URL = "https://zoom.us/oauth/token"


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != getattr(self.server, "expected_path", "/oauth/callback"):
            self.send_response(404)
            self.end_headers()
            return
        params = parse_qs(parsed.query)
        if "code" in params:
            self.server.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Authorization successful</h2>"
                b"<p>You can close this window and return to Claude.</p></body></html>"
            )
        elif "error" in params:
            self.server.auth_error = params["error"][0]
            self.send_response(400)
            self.end_headers()
            self.wfile.write(f"Error: {params['error'][0]}".encode())
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        pass


class ZoomOAuthHandler:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_store: TokenStore,
        redirect_uri: str = "http://localhost:8000/oauth/callback",
        logger: Optional[logging.Logger] = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.token_store = token_store
        self.logger = logger or logging.getLogger("zoom.oauth")

    def get_auth_url(self) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": "zoom_mcp_auth",
        }
        return f"{ZOOM_AUTH_URL}?{urlencode(params)}"

    def get_auth_headers(self) -> Dict[str, str]:
        data = self.token_store.load()
        if not data or not data.get("access_token"):
            raise RuntimeError("No access token; call ensure_authenticated first")
        return {
            "Authorization": f"{data.get('token_type', 'Bearer')} {data['access_token']}"
        }

    async def ensure_authenticated(self) -> bool:
        if not self.token_store.is_expired():
            return True
        data = self.token_store.load()
        if data and data.get("refresh_token"):
            if await self.refresh_access_token():
                return True
        return await self._run_browser_flow()

    async def refresh_access_token(self) -> bool:
        data = self.token_store.load()
        if not data or not data.get("refresh_token"):
            return False
        try:
            response = await request_with_retry(
                "POST", ZOOM_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": data["refresh_token"],
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )
        except Exception as e:
            self.logger.error("Token refresh failed: %s", e)
            return False
        if response.status_code != 200:
            self.logger.error("Token refresh HTTP %d", response.status_code)
            return False
        return self._save_token_response(
            response.json(), existing_refresh=data["refresh_token"]
        )

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

    async def _run_browser_flow(self, timeout_seconds: int = 300) -> bool:
        parsed = urlparse(self.redirect_uri)
        port = parsed.port or 8000
        callback_path = parsed.path or "/oauth/callback"

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("localhost", port))
        except OSError:
            self.logger.error("Port %d already in use", port)
            return False

        server = HTTPServer(("localhost", port), _CallbackHandler)
        server.expected_path = callback_path
        server.auth_code = None
        server.auth_error = None

        def serve():
            while server.auth_code is None and server.auth_error is None:
                server.handle_request()

        threading.Thread(target=serve, daemon=True).start()
        webbrowser.open(self.get_auth_url())
        loop_start = asyncio.get_event_loop().time()
        while server.auth_code is None and server.auth_error is None:
            await asyncio.sleep(0.1)
            if asyncio.get_event_loop().time() - loop_start > timeout_seconds:
                self.logger.error("OAuth callback timeout")
                server.server_close()
                return False
        server.server_close()
        if server.auth_error or not server.auth_code:
            return False
        return await self._exchange_code(server.auth_code)

    async def _exchange_code(self, code: str) -> bool:
        try:
            r = await request_with_retry(
                "POST", ZOOM_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )
        except Exception as e:
            self.logger.error("Code exchange failed: %s", e)
            return False
        if r.status_code != 200:
            self.logger.error("Code exchange HTTP %d: %s", r.status_code, r.text)
            return False
        return self._save_token_response(r.json())

    async def make_authenticated_request(
        self, method: str, url: str, **kwargs
    ) -> httpx.Response:
        if not await self.ensure_authenticated():
            raise RuntimeError("Authentication failed")
        headers = kwargs.get("headers", {})
        headers.update(self.get_auth_headers())
        kwargs["headers"] = headers
        response = await request_with_retry(method, url, **kwargs)
        if response.status_code == 401 and await self.refresh_access_token():
            headers.update(self.get_auth_headers())
            kwargs["headers"] = headers
            response = await request_with_retry(method, url, **kwargs)
        return response
