#!/usr/bin/env python3
"""
OAuth Handler Base Class for MCP Servers
Provides standardized OAuth2 flow implementation.
"""

import asyncio
import json
import socket
import threading
import time
import webbrowser
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Optional, Any
from urllib.parse import urlencode, parse_qs, urlparse
import logging
import httpx

from .token_manager import TokenManager


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler for OAuth callback"""

    def do_GET(self):
        parsed_url = urlparse(self.path)
        query_params = parse_qs(parsed_url.query)

        expected_path = getattr(self.server, 'expected_path', '/callback')
        if parsed_url.path != expected_path:
            self.send_response(404)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        if 'code' in query_params:
            self.server.auth_code = query_params['code'][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"""
            <html>
                <head><title>OAuth Success</title></head>
                <body>
                    <h2>Authorization Successful!</h2>
                    <p>You can close this window and return to the application.</p>
                    <script>setTimeout(function(){ window.close(); }, 3000);</script>
                </body>
            </html>
            """)
        elif 'error' in query_params:
            self.server.auth_error = query_params['error'][0]
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(f"""
            <html>
                <head><title>OAuth Error</title></head>
                <body>
                    <h2>Authorization Failed</h2>
                    <p>Error: {query_params['error'][0]}</p>
                    <p>You can close this window and try again.</p>
                </body>
            </html>
            """.encode())
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"Invalid callback")

    def log_message(self, format, *args):
        """Suppress default HTTP server logs"""
        pass


class OAuthHandler(ABC):
    """
    Base class for OAuth2 authentication handlers.

    Provides standardized OAuth2 flow with:
    - Authorization code flow
    - Token refresh
    - Secure token storage
    - Local callback server
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str = "http://localhost:9876/callback",
        scopes: Optional[list] = None,
        logger: Optional[logging.Logger] = None
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes or []
        self.logger = logger or logging.getLogger(f"oauth_{self.__class__.__name__}")

        service_name = self.__class__.__name__.lower().replace('oauthhandler', '')
        self.token_manager = TokenManager(service_name, logger=self.logger)
        self.client = httpx.AsyncClient(timeout=30.0)

    @abstractmethod
    def get_auth_url(self) -> str:
        pass

    @abstractmethod
    def get_token_url(self) -> str:
        pass

    @abstractmethod
    def get_refresh_url(self) -> str:
        pass

    async def ensure_authenticated(self) -> bool:
        token_data = self.token_manager.load_tokens()

        if token_data and not self.token_manager.is_token_expired(token_data):
            self.logger.debug("Valid tokens found")
            return True

        if token_data and token_data.get("refresh_token"):
            self.logger.info("Access token expired, attempting refresh")
            return await self._refresh_access_token()

        self.logger.info("No valid tokens found, initiating OAuth flow")
        return await self._authenticate_user()

    async def _authenticate_user(self) -> bool:
        try:
            parsed = urlparse(self.redirect_uri)
            port = parsed.port or 8000
            callback_path = parsed.path or "/callback"

            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('localhost', port))
            except OSError:
                self.logger.error(f"Port {port} is already in use")
                return False

            server = HTTPServer(('localhost', port), OAuthCallbackHandler)
            server.expected_path = callback_path
            server.auth_code = None
            server.auth_error = None

            server_thread = threading.Thread(target=self._run_callback_server, args=(server,))
            server_thread.daemon = True
            server_thread.start()

            auth_url = self.get_auth_url()
            self.logger.info("Opening browser for authorization")
            webbrowser.open(auth_url)

            timeout = 300
            start_time = asyncio.get_event_loop().time()

            while server.auth_code is None and server.auth_error is None:
                await asyncio.sleep(0.1)
                if asyncio.get_event_loop().time() - start_time > timeout:
                    self.logger.error("OAuth callback timeout")
                    server.server_close()
                    return False

            server.server_close()

            if server.auth_error:
                self.logger.error(f"OAuth authorization failed: {server.auth_error}")
                return False

            if not server.auth_code:
                self.logger.error("No authorization code received")
                return False

            return await self._exchange_code_for_token(server.auth_code)

        except Exception as e:
            self.logger.error(f"Authentication failed: {e}")
            return False

    def _run_callback_server(self, server):
        try:
            while server.auth_code is None and server.auth_error is None:
                server.handle_request()
        except Exception as e:
            self.logger.error(f"Callback server error: {e}")

    async def _exchange_code_for_token(self, code: str) -> bool:
        try:
            response = await self.client.post(
                self.get_token_url(),
                data={
                    'grant_type': 'authorization_code',
                    'code': code,
                    'redirect_uri': self.redirect_uri,
                    'client_id': self.client_id,
                    'client_secret': self.client_secret
                }
            )

            if response.status_code != 200:
                self.logger.error(f"Token exchange failed: {response.text}")
                return False

            token_data = response.json()
            return self._save_token_response(token_data)

        except Exception as e:
            self.logger.error(f"Token exchange error: {e}")
            return False

    async def _refresh_access_token(self) -> bool:
        token_data = self.token_manager.load_tokens()
        if not token_data or not token_data.get("refresh_token"):
            self.logger.warning("No refresh token available, need to re-authenticate")
            return await self._authenticate_user()

        try:
            response = await self.client.post(
                self.get_refresh_url(),
                data={
                    'grant_type': 'refresh_token',
                    'refresh_token': token_data["refresh_token"],
                    'client_id': self.client_id,
                    'client_secret': self.client_secret
                }
            )

            if response.status_code != 200:
                self.logger.error(f"Token refresh failed: {response.text}")
                return await self._authenticate_user()

            new_token_data = response.json()
            return self._save_token_response(new_token_data, token_data["refresh_token"])

        except Exception as e:
            self.logger.error(f"Token refresh error: {e}")
            return await self._authenticate_user()

    def _save_token_response(self, token_data: Dict, existing_refresh_token: Optional[str] = None) -> bool:
        try:
            access_token = token_data.get('access_token')
            if not access_token:
                self.logger.error("No access token in response")
                return False

            refresh_token = token_data.get('refresh_token', existing_refresh_token)
            expires_in = token_data.get('expires_in', 3600)
            expires_at = datetime.now() + timedelta(seconds=expires_in)

            success = self.token_manager.save_tokens(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                token_type=token_data.get('token_type', 'Bearer'),
                scope=token_data.get('scope'),
                additional_data={
                    'client_id': self.client_id,
                    'scopes': self.scopes
                }
            )

            if success:
                self.logger.info("Successfully obtained and saved tokens")
            else:
                self.logger.error("Failed to save tokens")

            return success
        except Exception as e:
            self.logger.error(f"Failed to process token response: {e}")
            return False

    def get_auth_headers(self) -> Dict[str, str]:
        token_data = self.token_manager.load_tokens()
        if not token_data or not token_data.get("access_token"):
            raise ValueError("No access token available")
        token_type = token_data.get("token_type", "Bearer")
        return {'Authorization': f'{token_type} {token_data["access_token"]}'}

    async def make_authenticated_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        if not await self.ensure_authenticated():
            raise Exception("Failed to authenticate")

        headers = kwargs.get('headers', {})
        headers.update(self.get_auth_headers())
        kwargs['headers'] = headers

        response = await self.client.request(method, url, **kwargs)

        if response.status_code == 401:
            self.logger.info("Got 401, attempting token refresh")
            if await self._refresh_access_token():
                headers.update(self.get_auth_headers())
                kwargs['headers'] = headers
                response = await self.client.request(method, url, **kwargs)

        return response

    async def cleanup(self):
        if self.client:
            await self.client.aclose()
