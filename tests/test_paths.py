import os
from pathlib import Path

from server import paths


def test_user_data_dir_macos(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setenv("HOME", "/Users/test")
    assert paths.user_data_dir() == Path("/Users/test/Library/Application Support/zoom-mcp")


def test_user_data_dir_linux_xdg(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "/tmp/xdg")
    assert paths.user_data_dir() == Path("/tmp/xdg/zoom-mcp")


def test_user_data_dir_linux_default(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", "/home/test")
    assert paths.user_data_dir() == Path("/home/test/.local/share/zoom-mcp")


def test_user_data_dir_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\test\AppData\Roaming")
    # Compare as string-suffix because Path on POSIX won't normalise Windows separators
    result = str(paths.user_data_dir())
    assert "C:\\Users\\test\\AppData\\Roaming" in result
    assert result.endswith("zoom-mcp")


def test_log_dir_macos(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setenv("HOME", "/Users/test")
    assert paths.log_dir() == Path("/Users/test/Library/Logs/zoom-mcp")


def test_ensure_dirs_creates_with_0700(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(paths, "log_dir", lambda: tmp_path / "logs")
    paths.ensure_dirs()
    assert (tmp_path / "data").exists()
    assert (tmp_path / "logs").exists()
    if os.name == "posix":
        assert oct((tmp_path / "data").stat().st_mode)[-3:] == "700"
