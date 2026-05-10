from server.files import MAX_FILE_BYTES, MAX_TEXT_BYTES, is_text_mime


def test_text_mime_detection():
    assert is_text_mime("text/plain")
    assert is_text_mime("text/markdown")
    assert is_text_mime("application/json")
    assert is_text_mime("application/x-yaml")
    assert not is_text_mime("application/pdf")
    assert not is_text_mime("image/png")
    assert not is_text_mime("application/zip")


def test_unknown_text_subtype_still_passes():
    assert is_text_mime("text/some-weird-subtype")


def test_empty_mime_returns_false():
    assert not is_text_mime("")
    assert not is_text_mime(None)


def test_size_constants():
    assert MAX_TEXT_BYTES == 1 * 1024 * 1024
    assert MAX_FILE_BYTES == 10 * 1024 * 1024
