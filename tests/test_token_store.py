import os
from datetime import datetime, timedelta

from server.token_store import TokenStore


def test_save_and_load_round_trip(tmp_path):
    store = TokenStore(tmp_path / "tokens.enc", tmp_path / "tokens.key")
    store.save("AT", "RT", datetime.now() + timedelta(hours=1))
    loaded = store.load()
    assert loaded["access_token"] == "AT"
    assert loaded["refresh_token"] == "RT"


def test_load_returns_none_when_no_file(tmp_path):
    store = TokenStore(tmp_path / "tokens.enc", tmp_path / "tokens.key")
    assert store.load() is None


def test_is_expired_with_5min_grace(tmp_path):
    store = TokenStore(tmp_path / "tokens.enc", tmp_path / "tokens.key")
    store.save("AT", "RT", datetime.now() + timedelta(minutes=2))
    assert store.is_expired() is True


def test_is_not_expired_when_far_future(tmp_path):
    store = TokenStore(tmp_path / "tokens.enc", tmp_path / "tokens.key")
    store.save("AT", "RT", datetime.now() + timedelta(hours=1))
    assert store.is_expired() is False


def test_delete_removes_files(tmp_path):
    store = TokenStore(tmp_path / "tokens.enc", tmp_path / "tokens.key")
    store.save("AT", "RT", datetime.now() + timedelta(hours=1))
    store.delete()
    assert not (tmp_path / "tokens.enc").exists()
    assert not (tmp_path / "tokens.key").exists()


def test_files_have_0600_perms(tmp_path):
    store = TokenStore(tmp_path / "tokens.enc", tmp_path / "tokens.key")
    store.save("AT", "RT", datetime.now() + timedelta(hours=1))
    if os.name == "posix":
        assert oct((tmp_path / "tokens.enc").stat().st_mode)[-3:] == "600"
        assert oct((tmp_path / "tokens.key").stat().st_mode)[-3:] == "600"
