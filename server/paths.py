"""Cross-platform user-data and log directory resolution. No external deps."""
import os
import sys
from pathlib import Path

APP_NAME = "zoom-mcp"


def user_data_dir() -> Path:
    """Return the OS-standard application-data directory for this app."""
    if sys.platform == "darwin":
        return Path(os.environ["HOME"]) / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / APP_NAME
    return Path(os.environ["HOME"]) / ".local" / "share" / APP_NAME


def log_dir() -> Path:
    """Return the OS-standard log directory for this app."""
    if sys.platform == "darwin":
        return Path(os.environ["HOME"]) / "Library" / "Logs" / APP_NAME
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / APP_NAME / "logs"
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / APP_NAME
    return Path(os.environ["HOME"]) / ".local" / "state" / APP_NAME


def token_file() -> Path:
    return user_data_dir() / "tokens.enc"


def token_key_file() -> Path:
    return user_data_dir() / "tokens.key"


def cache_db_file() -> Path:
    return user_data_dir() / "cache.sqlite"


def log_file() -> Path:
    return log_dir() / "zoom-mcp.log"


def ensure_dirs() -> None:
    """Create user-data and log dirs with restrictive perms (Unix)."""
    for p in (user_data_dir(), log_dir()):
        p.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(p, 0o700)
