from server.transcripts import find_transcript_file, parse_vtt


SAMPLE_VTT = """WEBVTT

1
00:00:00.000 --> 00:00:05.000
<v Alice>Hello and welcome.

2
00:00:05.000 --> 00:00:10.000
<v Bob>Thanks for having me.

3
00:00:10.000 --> 00:00:15.000
Plain text without speaker tag
"""


def test_parse_vtt_with_speakers():
    out = parse_vtt(SAMPLE_VTT)
    assert "[00:00] Alice: Hello and welcome." in out
    assert "[00:05] Bob: Thanks for having me." in out
    assert "[00:10] Plain text without speaker tag" in out


def test_parse_vtt_strips_webvtt_header():
    out = parse_vtt(SAMPLE_VTT)
    assert "WEBVTT" not in out


def test_parse_vtt_handles_empty():
    assert parse_vtt("") == ""


def test_parse_vtt_handles_malformed_returns_raw_fallback():
    out = parse_vtt("just some text without VTT formatting")
    assert "just some text" in out


def test_parse_vtt_skips_cue_identifier_numbers():
    out = parse_vtt(SAMPLE_VTT)
    # Lines like "1", "2", "3" should be skipped — they shouldn't appear standalone
    lines = out.splitlines()
    # Cue numbers shouldn't appear as their own lines
    assert "1" not in lines
    assert "2" not in lines


def test_parse_vtt_skips_NOTE_blocks():
    vtt = """WEBVTT

NOTE This is a note

00:00:00.000 --> 00:00:01.000
Text here
"""
    out = parse_vtt(vtt)
    assert "NOTE" not in out
    assert "Text here" in out


def test_find_transcript_file_prefers_TRANSCRIPT():
    files = [
        {"file_type": "MP4", "id": "1"},
        {"file_type": "CC", "id": "2"},
        {"file_type": "TRANSCRIPT", "id": "3"},
    ]
    assert find_transcript_file(files)["id"] == "3"


def test_find_transcript_file_falls_back_to_CC():
    files = [
        {"file_type": "MP4", "id": "1"},
        {"file_type": "CC", "id": "2"},
    ]
    assert find_transcript_file(files)["id"] == "2"


def test_find_transcript_file_returns_none_when_no_transcript():
    files = [{"file_type": "MP4", "id": "1"}]
    assert find_transcript_file(files) is None
