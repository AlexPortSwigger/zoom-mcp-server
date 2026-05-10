"""Meeting transcript download and VTT parser. Never persists transcript content."""
import re
from typing import Optional

from .endpoints import API_BASE
from .http_client import request_with_retry

_TIMESTAMP_RE = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2})\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}"
)
_SPEAKER_RE = re.compile(r"^<v\s+([^>]+)>(.*)$")


def parse_vtt(vtt: str) -> str:
    """Convert WEBVTT text to '[HH:MM] Speaker: text' lines."""
    lines = vtt.splitlines()
    out = []
    current_ts: Optional[str] = None
    saw_timestamp = False
    for raw in lines:
        line = raw.strip()
        if not line or line == "WEBVTT" or line.startswith("NOTE"):
            current_ts = None
            continue
        m = _TIMESTAMP_RE.match(line)
        if m:
            saw_timestamp = True
            hh, mm, ss = m.groups()
            # Use HH:MM for content >= 1 hour, MM:SS otherwise
            if int(hh) > 0:
                current_ts = f"[{hh}:{mm}]"
            else:
                current_ts = f"[{mm}:{ss}]"
            continue
        if line.isdigit():
            continue
        speaker_m = _SPEAKER_RE.match(line)
        if speaker_m:
            speaker, text = speaker_m.groups()
            prefix = current_ts or ""
            out.append(f"{prefix} {speaker}: {text}".strip())
        else:
            prefix = current_ts or ""
            out.append(f"{prefix} {line}".strip())
        current_ts = None
    if not saw_timestamp:
        return vtt.strip()
    return "\n".join(out)


def find_transcript_file(recording_files: list) -> Optional[dict]:
    """Pick the best transcript file from a recording_files manifest."""
    for f in recording_files:
        if f.get("file_type") == "TRANSCRIPT":
            return f
    for f in recording_files:
        if f.get("file_type") == "CC":
            return f
    return None


async def fetch_meeting_transcript(oauth_handler, meeting_id: str) -> str:
    """Download and parse the transcript for a given meeting."""
    r = await oauth_handler.make_authenticated_request(
        "GET", f"{API_BASE}/meetings/{meeting_id}/recordings",
    )
    if r.status_code == 404:
        raise RuntimeError("No recording exists for this meeting.")
    if r.status_code != 200:
        raise RuntimeError(
            f"Recording fetch failed: HTTP {r.status_code}: {r.text}"
        )

    files = r.json().get("recording_files", [])
    transcript_file = find_transcript_file(files)
    if not transcript_file:
        raise RuntimeError(
            "Recording exists but no transcript was generated. "
            "Free Zoom plans do not include transcription."
        )

    download_url = transcript_file.get("download_url")
    if not download_url:
        raise RuntimeError("Transcript file has no download URL")

    size = transcript_file.get("file_size", 0)
    if size and size > 50 * 1024 * 1024:
        raise RuntimeError(
            f"Transcript file too large ({size} bytes); fetch via Zoom UI."
        )

    headers = oauth_handler.get_auth_headers()
    dr = await request_with_retry("GET", download_url, headers=headers)
    if dr.status_code != 200:
        raise RuntimeError(f"Transcript download failed: HTTP {dr.status_code}")
    return parse_vtt(dr.text)
