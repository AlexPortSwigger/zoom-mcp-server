#!/usr/bin/env python3
"""
Zoom OAuth Handler
Implements Zoom-specific OAuth2 flow using standardized utilities
"""

from urllib.parse import urlencode
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from utils import OAuthHandler


class ZoomOAuthHandler(OAuthHandler):
    """Zoom-specific OAuth implementation"""

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str = None, logger=None):
        redirect_uri = redirect_uri or "http://localhost:8000/oauth/callback"

        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scopes=[],  # Scopes configured on the app in Zoom Marketplace
            logger=logger
        )

        self.auth_base_url = "https://zoom.us/oauth/authorize"
        self.token_base_url = "https://zoom.us/oauth/token"

    def get_auth_url(self) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": "zoom_mcp_auth",
        }
        if self.scopes:
            params["scope"] = " ".join(self.scopes)
        return f"{self.auth_base_url}?{urlencode(params)}"

    def get_token_url(self) -> str:
        return self.token_base_url

    def get_refresh_url(self) -> str:
        return self.token_base_url
