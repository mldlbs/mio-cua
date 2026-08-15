"""User-confirmation gate for high-risk actions.

A blocking desktop Yes/No dialog with a timeout that auto-denies (fail-closed).
Denial returns ``retryable=False`` upstream so the agent never retries a
rejected action. Set ``MIO_CUA_CONFIRM_OFF=1`` (or ``enabled=False``) to skip
the prompt entirely for headless/automation runs.
"""

import os
import threading

from mio_cua.safety.risk import HIGH_RISK

_DIALOG_TITLE = "mio-cua — 高风险操作确认"

MB_YESNO = 0x04
MB_ICONWARNING = 0x30
MB_DEFBUTTON2 = 0x100
MB_TOPMOST = 0x40000
IDYES = 6
WM_CLOSE = 0x0010


def _message_box(text, title):
    """Show a blocking Yes/No dialog; returns the Win32 result code."""
    import ctypes
    return ctypes.windll.user32.MessageBoxW(
        None, text, title, MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2 | MB_TOPMOST,
    )


def _ask(title, text, timeout_s, dialog=_message_box) -> bool:
    """Show a confirm/deny dialog with a timeout that auto-denies.

    Any outcome other than an explicit YES (No, Esc, WM_CLOSE from the
    timeout, or a dialog error) is treated as a denial -- fail-closed.
    """
    result = {}

    def _show():
        try:
            result["value"] = dialog(text, title)
        except Exception as e:
            result["error"] = e

    t = threading.Thread(target=_show, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        _close_dialog(title)
        t.join(1.0)
        return False
    if "error" in result:
        return False
    return result.get("value") == IDYES


def _close_dialog(title):
    """Post WM_CLOSE to the dialog so the blocked thread can exit."""
    import ctypes
    try:
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        if hwnd:
            ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    except Exception:
        pass


class Confirmation:
    def __init__(self, timeout_s: float = 30.0, enabled: bool = None):
        self.timeout_s = timeout_s
        if enabled is None:
            enabled = os.environ.get("MIO_CUA_CONFIRM_OFF", "0") != "1"
        self.enabled = enabled

    def confirm(self, tool_name: str, params=None) -> bool:
        """Ask the user before a high-risk tool runs.

        Returns True (approved) or False (denied / timed out / disabled path
        returns True without prompting).
        """
        if not self.enabled:
            return True
        return _ask(_DIALOG_TITLE, self._describe(tool_name, params), self.timeout_s)

    @staticmethod
    def _describe(tool_name, params) -> str:
        why = HIGH_RISK.get(tool_name, tool_name)
        p = ", ".join(f"{k}={v!r}" for k, v in (params or {}).items())
        return (f"mio-cua 想执行高风险操作:\n\n{tool_name}\n{why}\n"
                f"参数: {p or '(无)'}\n\n确认执行？")
