#!/usr/bin/env python3
"""
Token Manager for MCP Servers
Provides secure token storage and management for OAuth-enabled services.
"""

import json
import os
import stat
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List
import logging
from cryptography.fernet import Fernet
from pathlib import Path
import base64


class TokenManager:
    """
    Secure token storage and management for OAuth services.

    Features:
    - Encrypted token storage (optional)
    - Automatic expiration tracking
    - Multi-service support
    - Secure file permissions
    """

    def __init__(
        self,
        service_name: str,
        token_dir: Optional[str] = None,
        encrypt_tokens: bool = True,
        logger: Optional[logging.Logger] = None
    ):
        self.service_name = service_name
        self.encrypt_tokens = encrypt_tokens
        self.logger = logger or logging.getLogger(f"token_manager_{service_name}")

        if token_dir:
            self.token_dir = Path(token_dir)
        else:
            self.token_dir = Path(__file__).parent.parent / "tokens"

        self.token_dir.mkdir(exist_ok=True, mode=0o700)
        self.token_file = self.token_dir / f"{service_name}_tokens.json"
        self.key_file = self.token_dir / f"{service_name}_key.key"

        self._encryption_key = None
        if self.encrypt_tokens:
            self._init_encryption()

    def _init_encryption(self):
        try:
            if self.key_file.exists():
                with open(self.key_file, 'rb') as f:
                    self._encryption_key = f.read()
            else:
                self._encryption_key = Fernet.generate_key()
                with open(self.key_file, 'wb') as f:
                    f.write(self._encryption_key)
                os.chmod(self.key_file, 0o600)
        except Exception as e:
            self.logger.warning(f"Failed to initialize encryption: {e}. Falling back to unencrypted storage.")
            self.encrypt_tokens = False

    def _encrypt_data(self, data: str) -> str:
        if not self.encrypt_tokens or not self._encryption_key:
            return data
        try:
            fernet = Fernet(self._encryption_key)
            encrypted = fernet.encrypt(data.encode())
            return base64.b64encode(encrypted).decode()
        except Exception as e:
            self.logger.error(f"Encryption failed: {e}")
            return data

    def _decrypt_data(self, encrypted_data: str) -> str:
        if not self.encrypt_tokens or not self._encryption_key:
            return encrypted_data
        try:
            fernet = Fernet(self._encryption_key)
            decoded = base64.b64decode(encrypted_data.encode())
            decrypted = fernet.decrypt(decoded)
            return decrypted.decode()
        except Exception as e:
            self.logger.error(f"Decryption failed: {e}")
            return encrypted_data

    def save_tokens(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        expires_in: Optional[int] = None,
        token_type: str = "Bearer",
        scope: Optional[str] = None,
        additional_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        try:
            if expires_at is None and expires_in is not None:
                expires_at = datetime.now() + timedelta(seconds=expires_in)

            token_data = {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at.isoformat() if expires_at else None,
                "token_type": token_type,
                "scope": scope,
                "created_at": datetime.now().isoformat(),
                "service_name": self.service_name
            }

            if additional_data:
                token_data.update(additional_data)

            json_data = json.dumps(token_data, indent=2)
            if self.encrypt_tokens:
                json_data = self._encrypt_data(json_data)

            with open(self.token_file, 'w') as f:
                f.write(json_data)
            os.chmod(self.token_file, 0o600)

            self.logger.info(f"Tokens saved successfully for {self.service_name}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save tokens: {e}")
            return False

    def load_tokens(self) -> Optional[Dict[str, Any]]:
        try:
            if not self.token_file.exists():
                return None

            with open(self.token_file, 'r') as f:
                content = f.read()

            if self.encrypt_tokens:
                content = self._decrypt_data(content)

            token_data = json.loads(content)

            if token_data.get("expires_at"):
                try:
                    token_data["expires_at"] = datetime.fromisoformat(token_data["expires_at"])
                except ValueError:
                    token_data["expires_at"] = None

            return token_data
        except Exception as e:
            self.logger.error(f"Failed to load tokens: {e}")
            return None

    def is_token_expired(self, token_data: Optional[Dict[str, Any]] = None) -> bool:
        if token_data is None:
            token_data = self.load_tokens()
        if not token_data:
            return True

        expires_at = token_data.get("expires_at")
        if not expires_at:
            return False

        if isinstance(expires_at, str):
            try:
                expires_at = datetime.fromisoformat(expires_at)
            except ValueError:
                return True

        return datetime.now() >= (expires_at - timedelta(minutes=5))

    def delete_tokens(self) -> bool:
        try:
            if self.token_file.exists():
                self.token_file.unlink()
            if self.key_file.exists() and self.encrypt_tokens:
                self.key_file.unlink()
            return True
        except Exception as e:
            self.logger.error(f"Failed to delete tokens: {e}")
            return False

    def get_token_status(self) -> Dict[str, Any]:
        token_data = self.load_tokens()
        if not token_data:
            return {
                "service": self.service_name,
                "has_tokens": False,
                "encrypted": self.encrypt_tokens,
                "status": "no_tokens"
            }

        is_expired = self.is_token_expired(token_data)
        has_refresh = bool(token_data.get("refresh_token"))

        status = {
            "service": self.service_name,
            "has_tokens": True,
            "encrypted": self.encrypt_tokens,
            "has_access_token": bool(token_data.get("access_token")),
            "has_refresh_token": has_refresh,
            "is_expired": is_expired,
            "created_at": token_data.get("created_at"),
            "expires_at": token_data.get("expires_at").isoformat() if token_data.get("expires_at") else None,
            "token_type": token_data.get("token_type", "Bearer"),
            "scope": token_data.get("scope")
        }

        if is_expired:
            status["status"] = "expired" if has_refresh else "expired_no_refresh"
        else:
            status["status"] = "valid"

        return status
