import ctypes
from ctypes import wintypes


def set_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def get_cursor():
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def get_active_window():
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetForegroundWindow.argtypes = []
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def get_active_window_rect():
    """Return (left, top, width, height) of the foreground window in screen px."""
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    hwnd = user32.GetForegroundWindow()
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def focus_window(title: str, exact: bool = False) -> bool:
    """Bring the window whose title matches `title` to the foreground.

    Uses the same robust focus path as ``bring_to_front`` (SwitchToThisWindow +
    retries), falling back to pywinauto for the rare window that only UIA sees.
    """
    if not title:
        return False
    for hwnd in _windows_matching_title(title, exact=exact):
        if _focus_latest([hwnd]):
            return True
    # UIA fallback for windows EnumWindows can't see.
    from pywinauto import Desktop
    try:
        for w in Desktop(backend="uia").windows():
            text = w.window_text()
            if (exact and text == title) or (not exact and title.lower() in text.lower()):
                w.set_focus()
                return True
    except Exception:
        pass
    return False


def bring_to_front(hint: str) -> bool:
    """Bring a top-level window to the foreground.

    Matches by process name first (works for classic win32 apps). For UWP apps
    (e.g. Calculator) the window is hosted by ApplicationFrameHost and only the
    window title reveals it, so fall back to title matching.
    """
    names = _proc_names(hint)
    if names:
        focused = _focus_latest(_windows_matching_process(names))
        if focused:
            return True
    # UWP fallback: focus the most recent window whose title contains a keyword
    # from the hint or its known display title.
    for title_kw in _title_keywords(hint):
        hwnds = _windows_matching_title(title_kw)
        if hwnds and _focus_latest(hwnds):
            return True
    return False


_TITLE_HINTS = {
    "calc": ("计算器", "calculator"),
    "calculator": ("计算器", "calculator"),
    "notepad": ("记事本", "notepad", "无标题"),
    "paint": ("画图", "paint"),
    "mspaint": ("画图", "paint"),
    "winword": ("word",),
    "excel": ("excel",),
    "powershell": ("powershell", "pwsh"),
    "pwsh": ("powershell", "pwsh"),
    "cmd": ("cmd", "命令提示符"),
    "explorer": ("explorer", "此电脑", "文件资源管理器"),
    "msedge": ("edge", "microsoft edge"),
    "edge": ("edge", "microsoft edge"),
    "chrome": ("chrome", "google chrome"),
}


def _title_keywords(hint: str) -> tuple:
    base = _process_base(hint)
    return _TITLE_HINTS.get(base, (base,))


def _windows_matching_title(keyword: str, exact: bool = False) -> list:
    import win32gui

    found = []
    kw = keyword.lower()

    def _cb(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            text = win32gui.GetWindowText(hwnd)
            if exact and text == keyword:
                found.append(hwnd)
            elif not exact and kw in text.lower():
                found.append(hwnd)
        except Exception:
            pass
        return True

    win32gui.EnumWindows(_cb, None)
    return found


def bring_file_to_front(path_hint: str) -> bool:
    """Focus the most recent window whose title mentions the given file name.

    Used by `launch` to reuse a window that already has a file open instead of
    spawning a duplicate app process.
    """
    import os

    name = os.path.basename(path_hint).lower()
    if not name:
        return False
    matches = []
    for hwnd in _top_level_windows():
        title = _window_text(hwnd)
        if name in title.lower():
            matches.append(hwnd)
    return _focus_latest(matches)


def _process_base(hint: str) -> str:
    import os

    return os.path.splitext(os.path.basename(hint.split()[0]))[0].lower()


# Process names differ from the command used to launch them (e.g. UWP apps).
_PROC_ALIASES = {
    "calc": ("calculatorapp", "calc"),
    "notepad": ("notepad",),
    "mspaint": ("mspaint",),
    "paint": ("mspaint",),
    "winword": ("winword",),
    "excel": ("excel",),
    "powershell": ("powershell", "pwsh"),
    "cmd": ("cmd",),
    "explorer": ("explorer",),
    "msedge": ("msedge",),
    "edge": ("msedge",),
    "chrome": ("chrome",),
}


def _proc_names(hint: str) -> tuple:
    return _PROC_ALIASES.get(_process_base(hint), (_process_base(hint),))


def _top_level_windows():
    import win32gui

    found = []

    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    win32gui.EnumWindows(_cb, None)
    return found


def _window_text(hwnd):
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextLengthW.argtypes = [wt.HWND]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _windows_matching_process(names: tuple) -> list:
    import ctypes
    import os
    import win32gui
    import win32process

    found = []

    def _cb(hwnd, _):
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not h:
                return True
            try:
                buf = ctypes.create_unicode_buffer(512)
                ctypes.windll.psapi.GetModuleFileNameExW(h, None, buf, 512)
                name = os.path.splitext(os.path.basename(buf.value or ""))[0].lower()
            finally:
                ctypes.windll.kernel32.CloseHandle(h)
        except Exception:
            return True
        if name not in names:
            return True
        # Skip invisible tool/IME windows and empty title bars: focusing them
        # steals the foreground into a black hole (e.g. 'Default IME').
        if not win32gui.IsWindowVisible(hwnd):
            return True
        if not win32gui.GetWindowText(hwnd):
            return True
        found.append(hwnd)
        return True

    win32gui.EnumWindows(_cb, None)
    return found


def _focus_latest(hwnds: list) -> bool:
    """Focus the most recently created (topmost in z-order) of the given windows."""
    import ctypes
    import time
    import win32con
    import win32gui

    if not hwnds:
        return False
    # EnumWindows enumerates top-to-bottom in z-order; the LAST match is the
    # most recently created one. Prefer the last non-empty match.
    hwnd = hwnds[-1]
    for attempt in range(3):
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.BringWindowToTop(hwnd)
            time.sleep(0.05)
            # A window from the same process becoming foreground counts: UWP
            # apps sometimes present a wrapper that differs from the matched hwnd.
            if _fg_owned_by(hwnds, win32gui.GetForegroundWindow()):
                return True
            # SwitchToThisWindow force-switches the foreground without the
            # foreground-lock restriction and avoids the ALT/IME pitfall.
            ctypes.windll.user32.SwitchToThisWindow.argtypes = [
                wintypes.HWND, ctypes.c_bool,
            ]
            ctypes.windll.user32.SwitchToThisWindow(hwnd, True)
            time.sleep(0.1)
            if _fg_owned_by(hwnds, win32gui.GetForegroundWindow()):
                return True
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.1)
            if _fg_owned_by(hwnds, win32gui.GetForegroundWindow()):
                return True
        except Exception:
            time.sleep(0.1)
    return False


def _fg_owned_by(candidates, fg):
    """True if the foreground hwnd is in `candidates` or shares a process with one.

    UWP apps (e.g. Calculator) present their real window through a host
    (ApplicationFrameHost) whose hwnd differs from the child window we matched;
    GetForegroundWindow then returns a *different* hwnd from the candidates even
    though the app IS in the foreground. Compare by process instead.
    """
    import win32gui
    import win32process

    if fg in candidates:
        return True
    try:
        _, fg_pid = win32process.GetWindowThreadProcessId(fg)
        for c in candidates:
            try:
                _, c_pid = win32process.GetWindowThreadProcessId(c)
            except Exception:
                continue
            if c_pid == fg_pid:
                return True
    except Exception:
        pass
    return False
