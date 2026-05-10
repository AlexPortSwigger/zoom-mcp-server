"""Logging filter that scrubs sensitive content from log records."""
import logging
import re

_BEARER_RE = re.compile(r"(Authorization:\s*)Bearer\s+\S+", re.IGNORECASE)
_QPARAM_RE = re.compile(
    r"(\b(?:search_key|code|access_token|refresh_token|client_secret)=)([^&\s]+)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_SENSITIVE_KEYS = {
    "access_token", "refresh_token", "client_secret",
    "code", "search_key", "message", "text", "body",
    "content", "transcript", "answer",
}


def _scrub_text(text: str) -> str:
    text = _BEARER_RE.sub(r"\1[redacted]", text)
    text = _QPARAM_RE.sub(r"\1[redacted]", text)
    text = _EMAIL_RE.sub("[email]", text)
    return text


def _scrub_value(v):
    if isinstance(v, dict):
        return {
            k: ("[redacted]" if k in _SENSITIVE_KEYS else _scrub_value(val))
            for k, val in v.items()
        }
    if isinstance(v, (list, tuple)):
        return type(v)(_scrub_value(x) for x in v)
    if isinstance(v, str):
        return _scrub_text(v)
    return v


class SensitiveFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _scrub_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = _scrub_value(record.args)
            else:
                record.args = tuple(_scrub_value(a) for a in record.args)
        return True
