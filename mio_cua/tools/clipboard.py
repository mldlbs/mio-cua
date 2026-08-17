"""Clipboard tools: read/write the Windows clipboard text.

``clipboard_get`` returns a STRUCTURED result (text / has_text / length) so the
agent can distinguish "empty clipboard" (not an error) from a clipboard access
failure (error, retryable). The agent verifies a copy by reading back the
clipboard and checking the content matches expectations.
"""

import json

from mio_cua.models.action_result import ActionResult


def clipboard_get(ctx):
    """Return the current clipboard text as a structured result.

    Result JSON: {"text": ..., "has_text": bool, "length": int}.
    Empty clipboard / no CF_UNICODETEXT -> text="" has_text=False (SUCCESS, not
    an error). OpenClipboard failure -> success=False, retryable=True.
    """
    import win32clipboard
    try:
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                text = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            else:
                text = ""
        finally:
            win32clipboard.CloseClipboard()
        data = {"text": text, "has_text": bool(text), "length": len(text)}
        return ActionResult(ctx.current_action_id, True, json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return ActionResult(ctx.current_action_id, False, f"clipboard unavailable: {e}", retryable=True)


def clipboard_set(ctx, text=None):
    """Put ``text`` on the clipboard. Combine with a ctrl+v to paste without
    typing (fast + reliable for long content)."""
    if text is None:
        return ActionResult(ctx.current_action_id, False, "text required", retryable=True)
    import win32clipboard
    try:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(str(text), win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
        return ActionResult(ctx.current_action_id, True, "clipboard set")
    except Exception as e:
        return ActionResult(ctx.current_action_id, False, str(e), retryable=True)
