import logging

from server.log_filter import SensitiveFilter


def _capture(msg, *args):
    rec = logging.LogRecord("test", logging.INFO, __file__, 0, msg, args, None)
    SensitiveFilter().filter(rec)
    return rec.getMessage()


def test_filter_redacts_bearer_token():
    out = _capture("Calling with Authorization: Bearer abc123def456")
    assert "abc123" not in out
    assert "[redacted]" in out


def test_filter_redacts_refresh_token_in_dict():
    out = _capture("Got %s", {"refresh_token": "xyz789", "expires_in": 3600})
    assert "xyz789" not in out
    assert "expires_in" in out


def test_filter_redacts_search_key_qparam():
    out = _capture("GET /messages?search_key=secret&page=1")
    assert "secret" not in out
    assert "page=1" in out


def test_filter_redacts_email_in_path():
    out = _capture("GET /users/jane.doe@example.com")
    assert "jane.doe@example.com" not in out
    assert "[email]" in out


def test_filter_does_not_redact_safe_messages():
    out = _capture("Tool zoom_list_channels completed in 0.42s")
    assert out == "Tool zoom_list_channels completed in 0.42s"
