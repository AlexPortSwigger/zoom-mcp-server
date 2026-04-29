#!/usr/bin/env python3
"""
Bootstrap launcher for the Zoom MCP server when installed as an MCPB bundle.

MCPB runs this with the user's system Python. It:
  1. Creates/updates a user-local venv (default: ~/.zoom-mcp/.venv)
  2. Installs requirements.txt into the venv (once, cached via hash)
  3. os.execv's into the venv's python running zoom_server.py

This avoids shipping compiled wheels (cryptography, cffi, pydantic-core) in
the bundle — those would be tied to a specific CPython ABI and platform.
"""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

BUNDLE_DIR = Path(__file__).resolve().parent
REQUIREMENTS = BUNDLE_DIR / "requirements.txt"
SERVER = BUNDLE_DIR / "zoom_server.py"


def _data_dir() -> Path:
    override = os.getenv("ZOOM_MCP_HOME")
    if override:
        return Path(os.path.expanduser(override))
    return Path.home() / ".zoom-mcp"


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _requirements_hash() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def _ensure_venv() -> Path:
    data = _data_dir()
    data.mkdir(parents=True, exist_ok=True)
    venv_dir = data / ".venv"
    python = _venv_python(venv_dir)
    stamp = venv_dir / ".requirements.sha256"
    want_hash = _requirements_hash()

    needs_create = not python.exists()
    needs_install = needs_create or not stamp.exists() or stamp.read_text().strip() != want_hash

    if needs_create:
        print(f"[zoom-mcp] creating venv at {venv_dir}", file=sys.stderr)
        # Shell out to `python -m venv` rather than calling venv.EnvBuilder directly:
        # on macOS framework Python, the inherited __PYVENV_LAUNCHER__ causes the
        # nested ensurepip call to resolve back to the launcher and get killed.
        env = {k: v for k, v in os.environ.items() if k != "__PYVENV_LAUNCHER__"}
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)], env=env)

    if needs_install:
        print("[zoom-mcp] installing dependencies (first run or requirements changed)...", file=sys.stderr)
        subprocess.check_call(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--quiet", "-r", str(REQUIREMENTS)],
        )
        stamp.write_text(want_hash)

    return python


def main() -> None:
    python = _ensure_venv()
    os.execv(str(python), [str(python), str(SERVER)])


if __name__ == "__main__":
    main()
