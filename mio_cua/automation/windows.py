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


def _process_name_of(pid) -> str:
    """Base process name for a pid (e.g. 'msedge'), or '' when unreadable."""
    import os

    try:
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(512)
            ctypes.windll.psapi.GetModuleFileNameExW(h, None, buf, 512)
            return os.path.splitext(os.path.basename(buf.value or ""))[0].lower()
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    except Exception:
        return ""


def get_active_process() -> str:
    """Base process name of the foreground window (e.g. 'msedge'), or ''.

    The window TITLE is whatever content the app is showing — an Edge window
    may be titled "MIO·HUB — 任务总线" and never mention Edge at all. The
    owning process is the only title-independent identity available.
    """
    import win32gui
    import win32process

    try:
        hwnd = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return _process_name_of(pid)
    except Exception:
        return ""


def matches_target(target: str, window_title=None, window_process=None) -> bool:
    """True when `target` names the given (or current foreground) window.

    `target` may be an app name ("Edge", "wechat") or a literal window-title
    substring. With no arguments the live foreground window is used. Passing
    only ``window_title`` (a stored string) restricts matching to the title —
    a title carries no process information, so an Edge window titled
    "MIO·HUB — 任务总线" cannot be recognized from its title alone. Pass
    ``window_process`` too (as Observations now do) to make it title-
    independent.
    """
    if not target:
        return False

    live = window_title is None and window_process is None
    if live:
        window_title = get_active_window()
        window_process = get_active_process()

    title = (window_title or "").lower()
    if target.lower() in title:
        return True

    # Known localized display titles (wechat -> 微信)
    if title:
        for kw in _title_keywords(target):
            if kw.lower() in title:
                return True

    # Owning-process match: the only identity a page title cannot hide.
    proc = (window_process or "").lower()
    if proc and proc in _proc_names(target):
        return True
    return False


def focus_window(title: str, exact: bool = False) -> bool:
    """Bring the window whose title matches `title` to the foreground.

    Matching strategy:
    1. Exact title match
    2. Process name of a known app (WeChat -> weixin, Edge -> msedge, ...)
    3. Known localized titles (WeChat -> 微信)
    4. Substring match

    Step 2 matters: a browser/tab window's title is the PAGE title, so it
    rarely contains the app name ("MIO·HUB — 任务总线" is an Edge window, not
    "Edge"). Matching the owning process is title-independent.
    """
    if not title:
        return False

    # Known localized UIA titles for the alias lookup in step 3.
    _UIA_TITLES = {
        "wechat": "微信",
        "chrome": "Chrome",
        "firefox": "Firefox",
        "edge": "Edge",
    }

    # 1. Exact title match
    for hwnd in _windows_matching_title(title, exact=True):
        if _focus_latest([hwnd]):
            return True

    # 2. Process-name match for known apps (title-independent).
    #    Only for recognized app names: a literal window title that happens to
    #    be a single unknown word must not waste an enumeration of every
    #    top-level process on the desktop.
    if _process_base(title) in _PROC_ALIASES:
        if _focus_latest(_windows_matching_process(_proc_names(title))):
            return True

    # 3. Known localized titles (WeChat's window says 微信, not "wechat")
    uia_title = _UIA_TITLES.get(title.lower())
    if uia_title:
        for hwnd in _windows_matching_title(uia_title, exact=False):
            if _focus_latest([hwnd]):
                return True

    # 4. Substring match
    for hwnd in _windows_matching_title(title, exact=False):
        if _focus_latest([hwnd]):
            return True

    # No match. Deliberately NO UIA full-desktop fallback: steps 1 and 4
    # already perform exact and substring matching via win32gui.EnumWindows
    # (which also filters IsWindowVisible), so a UIA pass over every top-level
    # window added no coverage — it only hung for minutes here.
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
    "wechat": ("微信", "weixin"),
    "weixin": ("微信", "weixin"),
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
    "wechat": ("weixin",),
    "weixin": ("weixin",),
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
    import win32gui
    import win32process

    found = []

    def _cb(hwnd, _):
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            name = _process_name_of(pid)
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


_TASKBAR_CLASS = "Shell_TrayWnd"
_TASKBAR_MAX_NODES = 200
_TASKBAR_MAX_DEPTH = 6


def locate_taskbar_hwnd() -> int:
    """Return the taskbar top-level window handle, or 0 when unavailable.

    Resolved by window class name only -- never by enumerating the desktop,
    which is what made the old focus_window UIA fallback hang.
    """
    import win32gui

    try:
        return int(win32gui.FindWindow(_TASKBAR_CLASS, None) or 0)
    except Exception:
        return 0


def enumerate_taskbar(
    hwnd: int,
    max_nodes: int = _TASKBAR_MAX_NODES,
    max_depth: int = _TASKBAR_MAX_DEPTH,
) -> tuple:
    """Walk the taskbar UIA subtree into ``[{name, kind, rect}]``.

    Returns ``(items, truncated)``. The root taskbar element itself is not
    included, only its descendants. Per-element property failures are skipped
    rather than aborting the walk.
    """
    from pywinauto import Desktop

    items = []
    truncated = False
    if not hwnd:
        return items, truncated

    try:
        root = Desktop(backend="uia").window(handle=hwnd)
    except Exception:
        return items, truncated

    try:
        root_children = list(root.children())
    except Exception:
        root_children = []
    stack = [(child, 1) for child in reversed(root_children)]
    while stack:
        node, depth = stack.pop()
        if len(items) >= max_nodes:
            truncated = True
            break
        if depth > max_depth:
            continue

        name = ""
        kind = ""
        rect = [0, 0, 0, 0]
        try:
            name = node.window_text() or ""
        except Exception:
            pass
        try:
            kind = node.friendly_class_name() or ""
        except Exception:
            pass
        try:
            r = node.rectangle()
            rect = [int(r.left), int(r.top), int(r.right) - int(r.left), int(r.bottom) - int(r.top)]
        except Exception:
            pass
        items.append({"name": name, "kind": kind, "rect": rect})

        if depth >= max_depth:
            continue
        try:
            children = list(node.children())
        except Exception:
            children = []
        for child in reversed(children):
            stack.append((child, depth + 1))

    return items, truncated


def find_taskbar_element(
    hwnd: int,
    target: str,
    max_nodes: int = _TASKBAR_MAX_NODES,
    max_depth: int = _TASKBAR_MAX_DEPTH,
) -> tuple:
    """Return ``(element, matched_name, candidate_count)`` for a substring target.

    Walks the same subtree as :func:`enumerate_taskbar` but hands back the live
    UIA wrapper so the caller can invoke it. Every matching name is counted so
    the caller can tell an ambiguous target from a precise one.
    """
    from pywinauto import Desktop

    if not hwnd or not target:
        return None, "", 0
    needle = str(target).strip().lower()
    if not needle:
        return None, "", 0

    try:
        root = Desktop(backend="uia").window(handle=hwnd)
        root_children = list(root.children())
    except Exception:
        return None, "", 0

    first = None
    first_name = ""
    candidates = 0
    seen = 0
    stack = [(child, 1) for child in reversed(root_children)]
    while stack and seen < max_nodes:
        node, depth = stack.pop()
        seen += 1

        try:
            name = node.window_text() or ""
        except Exception:
            name = ""
        if needle in name.lower():
            candidates += 1
            if first is None:
                first, first_name = node, name

        if depth >= max_depth:
            continue
        try:
            children = list(node.children())
        except Exception:
            children = []
        for child in reversed(children):
            stack.append((child, depth + 1))

    if first is None:
        return None, "", 0
    return first, first_name, candidates


# The app frame that defines "this window" inside the scene. Every consumer
# (planner layout, runtime observation, agent loop) needs the SAME frame -- it
# was found by three copies of this heuristic, so it lives here once.
#
# CONFIRMED against live UIA (2026-10-05, Edge): the window ROOT control is now
# emitted by automation.uia.get_elements (it used to be missing -- descendants()
# excludes the window itself), so the scene carries a group with role=="window"
# whose bbox IS the whole window. That is the frame, identified structurally.
# The shell-class markers stay only as a legacy hint; largest-group is the last
# resort if no window role is present (e.g. synthetic scenes in tests).
_FRAME_ROLE_MARKERS = ("MMUIRenderSubWindow", "Weixin")
_FRAME_ROLE = "window"


def frame_bbox(scene_nodes):
    """The active app's window frame bbox, or None.

    The frame is what a sidebar is relative to: a window on a secondary screen
    sits at x=840, so an absolute ``x < 300`` mislabels its chat list as the
    main panel.

    Preference order (most to least structural):
      1. the group whose UIA ``role`` is "window" -- the real window root;
      2. a group whose shell-class marker leaked into its text (legacy hint);
      3. the largest group (synthetic scenes without a window root).
    """
    groups = [n for n in (scene_nodes or [])
              if getattr(n, "type", "") == "group" and getattr(n, "bbox", None)]
    if not groups:
        return None
    for n in groups:
        if (getattr(n, "role", "") or "").strip().lower() == _FRAME_ROLE:
            return n.bbox
    for n in groups:
        semantic = getattr(n, "semantic", "") or ""
        if any(marker in semantic for marker in _FRAME_ROLE_MARKERS):
            return n.bbox
    return max(groups, key=lambda n: n.bbox[2] * n.bbox[3]).bbox
