import json

from mio_cua.tools.clipboard import clipboard_get, clipboard_set
from mio_cua.models.action_result import ActionResult


class Ctx:
    current_action_id = "t"


def _read_clipboard():
    import win32clipboard
    win32clipboard.OpenClipboard()
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
            return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        return ""
    finally:
        win32clipboard.CloseClipboard()


def test_set_then_get_roundtrip():
    r = clipboard_set(Ctx(), text="hello 世界")
    assert r.success is True
    r2 = clipboard_get(Ctx())
    assert r2.success is True
    data = json.loads(r2.message)
    assert data["text"] == "hello 世界"
    assert data["has_text"] is True
    assert data["length"] == len("hello 世界")


def test_get_empty_clipboard_is_success():
    # clear clipboard first
    clipboard_set(Ctx(), text="")
    r = clipboard_get(Ctx())
    assert r.success is True
    data = json.loads(r.message)
    assert data["text"] == ""
    assert data["has_text"] is False
    assert data["length"] == 0


def test_set_requires_text():
    r = clipboard_set(Ctx())
    assert r.success is False
    assert r.retryable is True


def test_get_returns_structured_json():
    clipboard_set(Ctx(), text="abc")
    r = clipboard_get(Ctx())
    data = json.loads(r.message)
    assert set(data.keys()) == {"text", "has_text", "length"}
    assert data == {"text": "abc", "has_text": True, "length": 3}
