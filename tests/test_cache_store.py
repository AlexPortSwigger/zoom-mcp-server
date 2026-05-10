from server.cache.store import CacheStore


def test_put_and_get_channels(tmp_path):
    store = CacheStore(tmp_path / "cache.db")
    store.put_channels([
        {"id": "c1", "name": "general", "type": 3, "member_count": 50},
        {"id": "c2", "name": "devs", "type": 1, "member_count": 8, "starred": True},
    ])
    rows = store.get_channels()
    assert len(rows) == 2
    by_name = {r["name"]: r for r in rows}
    assert by_name["devs"]["starred"] == 1


def test_ttl_eviction(tmp_path, monkeypatch):
    fake_now = [1000000]
    monkeypatch.setattr("server.cache.store._now_ms", lambda: fake_now[0] * 1000)
    store = CacheStore(tmp_path / "cache.db")
    store.put_channels([{"id": "c1", "name": "x", "type": 3}])
    fake_now[0] = 1000000 + 3601  # 1h+1s later
    assert store.get_channels(ttl_seconds=3600) == []


def test_starred_filter(tmp_path):
    store = CacheStore(tmp_path / "cache.db")
    store.put_channels([
        {"id": "c1", "name": "x", "type": 3, "starred": False},
        {"id": "c2", "name": "y", "type": 3, "starred": True},
    ])
    starred = store.get_channels(starred_only=True)
    assert len(starred) == 1
    assert starred[0]["name"] == "y"


def test_email_to_id(tmp_path):
    store = CacheStore(tmp_path / "cache.db")
    store.put_email_to_id("a@b.com", "U1")
    assert store.get_user_id_by_email("a@b.com") == "U1"


def test_get_channel_by_name_and_id(tmp_path):
    store = CacheStore(tmp_path / "cache.db")
    store.put_channels([{"id": "c1", "name": "general", "type": 3}])
    assert store.get_channel_by_name("general")["id"] == "c1"
    assert store.get_channel_by_id("c1")["name"] == "general"


def test_channel_members_round_trip(tmp_path):
    store = CacheStore(tmp_path / "cache.db")
    store.put_channel_members("C1", [
        {"id": "u1", "role": "owner"},
        {"id": "u2", "role": "member"},
    ])
    members = store.get_channel_members("C1")
    assert len(members) == 2
    assert {m["user_id"] for m in members} == {"u1", "u2"}


def test_put_contacts_builds_display_from_first_last_name(tmp_path):
    """Zoom returns first_name + last_name on contacts, not display_name."""
    store = CacheStore(tmp_path / "cache.db")
    store.put_contacts([
        {"id": "U1", "email": "a@b.com", "first_name": "Alice", "last_name": "Smith"},
        {"id": "U2", "email": "b@b.com", "first_name": "Bob"},  # no last_name
        {"id": "U3", "email": "c@b.com"},  # nothing — fallback to email
        {"id": "U4", "email": "d@b.com", "display_name": "Dave Direct"},  # explicit display_name preferred
    ])
    rows = {r["id"]: r for r in store.get_contacts()}
    assert rows["U1"]["display_name"] == "Alice Smith"
    assert rows["U2"]["display_name"] == "Bob"
    assert rows["U3"]["display_name"] == "c@b.com"
    assert rows["U4"]["display_name"] == "Dave Direct"


def test_clear_wipes_everything(tmp_path):
    store = CacheStore(tmp_path / "cache.db")
    store.put_channels([{"id": "c1", "name": "x", "type": 3}])
    store.put_email_to_id("a@b.com", "U1")
    store.put_shared_spaces([{"id": "s1", "name": "sp"}])
    store.clear_all()
    assert store.get_channels() == []
    assert store.get_user_id_by_email("a@b.com") is None
    assert store.get_shared_spaces() == []
