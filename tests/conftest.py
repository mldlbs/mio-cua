import ctypes
import ctypes.wintypes
import os
import sys

import pytest

# Do not pre-warm OmniParser in tests: it spawns a 10-20s model load on a
# background thread that would peg the CPU during the suite.
os.environ.setdefault("MIO_CUA_NO_PREWARM", "1")


def _has_interactive_desktop() -> bool:
    """True only when a real desktop session exists (foreground window with size).

    GitHub-hosted Windows runners run without an interactive session:
    ``GetForegroundWindow()`` returns 0, and screen capture / UIA / input either
    fail or return junk. Tests that genuinely need a desktop are marked
    ``@pytest.mark.desktop`` and skipped there, so headless CI reports real
    regressions instead of environment noise.

    Set ``MIO_TEST_NO_DESKTOP=1`` to exercise the headless path locally.
    """
    if os.environ.get("MIO_TEST_NO_DESKTOP") == "1":
        return False
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        rect = ctypes.wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        return (rect.right - rect.left) > 0 and (rect.bottom - rect.top) > 0
    except Exception:
        return False


HAS_DESKTOP = _has_interactive_desktop()


def pytest_collection_modifyitems(config, items):
    if HAS_DESKTOP:
        return
    skip = pytest.mark.skip(reason="needs an interactive desktop (headless CI)")
    for item in items:
        if "desktop" in item.keywords:
            item.add_marker(skip)
