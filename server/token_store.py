"""Fernet-encrypted OAuth token storage with restrictive file perms."""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet


class TokenStore:
    def __init__(self, token_file: Path, key_file: Path):
        self.token_file = Path(token_file)
        self.key_file = Path(key_file)

    def _key(self) -> bytes:
        if self.key_file.exists():
            return self.key_file.read_bytes()
        key = Fernet.generate_key()
        self.key_file.parent.mkdir(parents=True, exist_ok=True)
        self.key_file.write_bytes(key)
        if os.name == "posix":
            os.chmod(self.key_file, 0o600)
        return key

    def save(
        self,
        access_token: str,
        refresh_token: Optional[str],
        expires_at: datetime,
        token_type: str = "Bearer",
        scope: Optional[str] = None,
    ) -> None:
        data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at.isoformat(),
            "token_type": token_type,
            "scope": scope,
            "created_at": datetime.now().isoformat(),
        }
        plaintext = json.dumps(data).encode()
        ciphertext = Fernet(self._key()).encrypt(plaintext)
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_bytes(ciphertext)
        if os.name == "posix":
            os.chmod(self.token_file, 0o600)

    def load(self) -> Optional[Dict[str, Any]]:
        if not self.token_file.exists() or not self.key_file.exists():
            return None
        try:
            ciphertext = self.token_file.read_bytes()
            plaintext = Fernet(self._key()).decrypt(ciphertext)
            data = json.loads(plaintext.decode())
            data["expires_at"] = datetime.fromisoformat(data["expires_at"])
            return data
        except Exception:
            return None

    def is_expired(self, grace_minutes: int = 5) -> bool:
        data = self.load()
        if not data:
            return True
        return datetime.now() >= data["expires_at"] - timedelta(minutes=grace_minutes)

    def delete(self) -> None:
        for p in (self.token_file, self.key_file):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
