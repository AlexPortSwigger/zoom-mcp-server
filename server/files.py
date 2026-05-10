"""Chat file fetching with strict text-only MIME allow-list."""
from typing import Any, Dict

from .endpoints import API_BASE
from .http_client import request_with_retry

MAX_TEXT_BYTES = 1 * 1024 * 1024
MAX_FILE_BYTES = 10 * 1024 * 1024

_TEXT_MIMES = {
    "text/plain", "text/markdown", "text/csv", "text/html",
    "application/json", "application/xml", "text/xml",
    "application/x-yaml", "application/yaml",
    "application/x-toml", "application/toml",
}
_TEXT_PREFIXES = ("text/",)


def is_text_mime(mime: str) -> bool:
    if not mime:
        return False
    if mime in _TEXT_MIMES:
        return True
    return any(mime.startswith(p) for p in _TEXT_PREFIXES)


async def get_file(oauth_handler, file_id: str) -> Dict[str, Any]:
    """Return file metadata; for text MIME types, also fetch and inline text."""
    r = await oauth_handler.make_authenticated_request(
        "GET", f"{API_BASE}/chat/files/{file_id}",
    )
    if r.status_code != 200:
        raise RuntimeError(
            f"File metadata fetch failed: HTTP {r.status_code}: {r.text}"
        )
    meta = r.json()
    mime = meta.get("file_type") or meta.get("mime_type", "")
    size = int(meta.get("file_size", 0))
    download_url = meta.get("download_url")

    result: Dict[str, Any] = {
        "file_id": meta.get("id") or file_id,
        "name": meta.get("name") or meta.get("file_name"),
        "mime_type": mime,
        "size": size,
        "sender": meta.get("sender"),
        "posted_at": meta.get("date_time") or meta.get("posted_at"),
        "channel_id": meta.get("channel_id"),
        "download_url": download_url,
    }

    if is_text_mime(mime) and size <= MAX_TEXT_BYTES and download_url:
        headers = oauth_handler.get_auth_headers()
        dr = await request_with_retry("GET", download_url, headers=headers)
        if dr.status_code == 200:
            content = dr.content
            if len(content) > MAX_TEXT_BYTES:
                content = content[:MAX_TEXT_BYTES]
            try:
                result["text"] = content.decode("utf-8", errors="replace")
            except Exception:
                pass
    return result
