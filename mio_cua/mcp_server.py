"""MCP server for mio-cua: let any MCP client (Claude, Cursor, ...) control
this Windows machine's desktop, files and windows.

Exposes the agent's proven capabilities as MCP tools:
- filesystem: list_dir / make_dir / move_file / move_files
- window/launch: launch, focus_window, get_active_window
- input: click, type, key

Local stdio transport (the tools operate on the user's own desktop).
"""

import os
import sys
import time
from typing import List, Optional

from pydantic import Field
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mio_cua_mcp")

# Warm up OmniParser in the background at server start so the first
# mio_analyze_page call doesn't block on a 10-20s model cold-start. Load is
# CPU/GPU-bounded and runs on a low-priority daemon thread; the tools work fine
# without it (they lazy-load), this just hides the latency.
def _prewarm_omniparser():
    if os.environ.get("MIO_CUA_NO_PREWARM") == "1":
        return
    try:
        import threading
        def _do():
            try:
                from mio_cua.scene import omniparser
                omniparser._load()
            except Exception:
                pass
        t = threading.Thread(target=_do, name="omni-prewarm", daemon=True)
        t.start()
    except Exception:
        pass


_prewarm_omniparser()


from mio_cua.safety.confirm import Confirmation

CONFIRMATION = Confirmation()

# MCP tool name -> HIGH_RISK semantic key. New high-risk tools MUST be added
# here (and mirror destructiveHint: True on the @mcp.tool annotation).
_MCP_HIGH_RISK = {
    "mio_kill_process": "kill_process",
    "mio_close_window": "close_window",
}


def _confirm_mcp_tool(tool_name: str, params: dict) -> bool:
    """Return True if the tool is not high-risk, or the user confirmed it."""
    key = _MCP_HIGH_RISK.get(tool_name)
    if key is None:
        return True
    return CONFIRMATION.confirm(key, params)


class _StubCtx:
    """Minimal context satisfying mio-cua's tool signatures."""

    current_action_id = "mcp"
    finished_status = ""
    finished_summary = ""


def _run(func, *args, **kwargs):
    """Call a mio-cua tool and return its ActionResult message."""
    res = func(_StubCtx(), *args, **kwargs)
    if res.success:
        return res.message
    return f"Error: {res.message}"


# ---------------------------------------------------------------------------
# Filesystem tools
# ---------------------------------------------------------------------------

@mcp.tool(name="mio_list_dir", annotations={
    "title": "List a directory", "readOnlyHint": True,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_list_dir(path: str = Field(..., description="Filesystem path, e.g. C:/Users/x/Desktop")) -> str:
    """List files and directories under a path (files first, one per line).

    Use to inventory a folder before organizing it.
    """
    from mio_cua.tools.fs import list_dir
    return _run(list_dir, path=path)


@mcp.tool(name="mio_make_dir", annotations={
    "title": "Create a directory", "readOnlyHint": False,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_make_dir(path: str = Field(..., description="Directory path to create (recursively)")) -> str:
    """Create a directory (recursively) if it does not exist."""
    from mio_cua.tools.fs import make_dir
    return _run(make_dir, path=path)


@mcp.tool(name="mio_move_file", annotations={
    "title": "Move one file", "readOnlyHint": False,
    "destructiveHint": False, "idempotentHint": False, "openWorldHint": True,
})
async def mio_move_file(src: str = Field(..., description="Path of the file to move"),
                        dest: str = Field(..., description="Destination DIRECTORY; file moves inside keeping its name")) -> str:
    """Move ONE file into a directory. Refuses to overwrite."""
    from mio_cua.tools.fs import move_file
    return _run(move_file, src=src, dest=dest)


@mcp.tool(name="mio_move_files", annotations={
    "title": "Move many files into one directory", "readOnlyHint": False,
    "destructiveHint": False, "idempotentHint": False, "openWorldHint": True,
})
async def mio_move_files(files: List[str] = Field(..., description="List of file paths to move"),
                         dest: str = Field(..., description="Destination DIRECTORY for all files")) -> str:
    """Move a LIST of files into one directory in a single call (batch organize)."""
    from mio_cua.tools.fs import move_files
    return _run(move_files, files=files, dest=dest)


@mcp.tool(name="mio_read_file", annotations={
    "title": "Read a text file", "readOnlyHint": True,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_read_file(path: str = Field(..., description="Path of the file to read"),
                        max_chars: int = Field(default=2000, description="Max chars to return", ge=1, le=100000)) -> str:
    """Read a text file's first N characters (default 2000). Use to retrieve
    file contents the AI needs (e.g. numbers to compute on) without opening the
    file in an editor."""
    from mio_cua.tools.fs import read_file
    return _run(read_file, path=path, max_chars=max_chars)


@mcp.tool(name="mio_write_file", annotations={
    "title": "Write text to a file", "readOnlyHint": False,
    "destructiveHint": True, "idempotentHint": False, "openWorldHint": True,
})
async def mio_write_file(path: str = Field(..., description="Path to write"),
                         content: str = Field(..., description="Text content to write"),
                         mode: str = Field(default="create", description="create/append/write"),
                         allow_overwrite: bool = Field(default=False, description="Allow overwriting an existing file in write mode")) -> str:
    """Write text to a file. mode=create makes a new file (refuses if it exists),
    append adds to the end, write overwrites only with allow_overwrite=True.
    Creates parent directories. Content is UTF-8."""
    from mio_cua.tools.fs import write_file
    return _run(write_file, path=path, content=content, mode=mode, allow_overwrite=allow_overwrite)


@mcp.tool(name="mio_search_files", annotations={
    "title": "Search files by name/ext/content", "readOnlyHint": True,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_search_files(path: str = Field(..., description="Directory to search recursively"),
                           name: str = Field(default="", description="Filename substring (optional)"),
                           ext: str = Field(default="", description="Extension without dot, e.g. 'txt' (optional)"),
                           pattern: str = Field(default="", description="Content substring (optional)"),
                           max_results: int = Field(default=50, description="Max results", ge=1, le=500)) -> str:
    """Recursively search a directory for files by name substring, extension,
    and/or content pattern. Returns up to 50 matching paths."""
    from mio_cua.tools.fs import search_files
    return _run(search_files, path=path, name=name or None, ext=ext or None,
                pattern=pattern or None, max_results=max_results)


# ---------------------------------------------------------------------------
# Window / launch tools
# ---------------------------------------------------------------------------

@mcp.tool(name="mio_launch", annotations={
    "title": "Launch an app or open a file", "readOnlyHint": False,
    "destructiveHint": False, "idempotentHint": False, "openWorldHint": True,
})
async def mio_launch(command: str = Field(..., description="Command or path to launch, e.g. 'notepad', 'calc', 'msedge https://x.com'")) -> str:
    """Launch a program/command or open a file path (browser URLs resolved)."""
    from mio_cua.tools.launch import launch
    return _run(launch, command=command)


@mcp.tool(name="mio_focus_window", annotations={
    "title": "Focus a window", "readOnlyHint": False,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_focus_window(title: str = Field(..., description="Window title (or substring) to focus")) -> str:
    """Bring a window whose title matches to the foreground."""
    from mio_cua.tools.focus_window import focus_window
    return _run(focus_window, title=title)


@mcp.tool(name="mio_get_active_window", annotations={
    "title": "Get active window title", "readOnlyHint": True,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_get_active_window() -> str:
    """Return the title of the currently focused window."""
    from mio_cua.automation.windows import get_active_window
    return get_active_window() or "(no foreground window)"


# ---------------------------------------------------------------------------
# Input tools (click / type / key)
# ---------------------------------------------------------------------------

@mcp.tool(name="mio_click", annotations={
    "title": "Click at coordinates", "readOnlyHint": False,
    "destructiveHint": False, "idempotentHint": False, "openWorldHint": True,
})
async def mio_click(x: int = Field(..., description="Screen X coordinate"),
                    y: int = Field(..., description="Screen Y coordinate"),
                    button: str = Field(default="left", description="Mouse button: left or right")) -> str:
    """Click the mouse at screen coordinates (x,y)."""
    from mio_cua.automation.input_controller import InputController
    from mio_cua.models.action import Action
    ctrl = InputController()
    r = ctrl.execute(Action(id="mcp", type="click",
                            params={"x": x, "y": y, "button": button}))
    return "clicked" if r.sent else f"Error: {r.error}"


@mcp.tool(name="mio_type", annotations={
    "title": "Type text into focused field", "readOnlyHint": False,
    "destructiveHint": False, "idempotentHint": False, "openWorldHint": True,
})
async def mio_type(text: str = Field(..., description="Text to type into the focused field")) -> str:
    """Type text (clipboard paste) into the focused field."""
    from mio_cua.automation.input_controller import InputController
    from mio_cua.models.action import Action
    ctrl = InputController()
    r = ctrl.execute(Action(id="mcp", type="type", params={"text": text}))
    return "typed" if r.sent else f"Error: {r.error}"


@mcp.tool(name="mio_key", annotations={
    "title": "Send keyboard key/combo", "readOnlyHint": False,
    "destructiveHint": False, "idempotentHint": False, "openWorldHint": True,
})
async def mio_key(keys: str = Field(..., description="Key or combo, e.g. 'enter', 'ctrl+s', 'alt+F4'")) -> str:
    """Send a key or key combination (e.g. 'enter', 'ctrl+s')."""
    from mio_cua.automation.input_controller import InputController
    from mio_cua.models.action import Action
    ctrl = InputController()
    r = ctrl.execute(Action(id="mcp", type="key", params={"keys": keys}))
    return "sent" if r.sent else f"Error: {r.error}"


# ---------------------------------------------------------------------------
# Perception tools (let the AI client "see" the screen before acting)
# ---------------------------------------------------------------------------

@mcp.tool(name="mio_observe_scene", annotations={
    "title": "Observe the active window as a scene", "readOnlyHint": True,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_observe_scene(max_elements: int = Field(default=60, description="Max elements to list", ge=1, le=200)) -> str:
    """Inspect the active window: its title and a list of UI elements (buttons,
    text, inputs) with text and screen coordinates. Use BEFORE clicking/typing
    so you can target real coordinates instead of guessing."""
    try:
        from mio_cua.perception.perception import Perception
        obs = Perception().observe()
        lines = [f"Active window: {obs.active_window or '(none)'}"]
        scene = getattr(obs, "scene", None)
        nodes = list(scene.nodes) if scene is not None else []
        if not nodes:
            return "\n".join(lines) + "\n(no elements detected)"
        # text-bearing, actionable nodes first
        nodes.sort(key=lambda n: (0 if (n.text or "").strip() else 1, n.bbox[1], n.bbox[0]))
        for n in nodes[:max_elements]:
            label = (n.semantic or n.text or f"({n.type})").strip()
            src = (n.metadata or {}).get("source") or n.source or "?"
            conf = getattr(n, "confidence", None)
            conf_s = f" conf={conf:.2f}" if isinstance(conf, (int, float)) else ""
            lines.append(f"- id={n.id} {label!r} [{n.type}] bbox={n.bbox} src={src}{conf_s}")
        if len(nodes) > max_elements:
            lines.append(f"... and {len(nodes) - max_elements} more")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool(name="mio_screenshot", annotations={
    "title": "Screenshot the active window", "readOnlyHint": True,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_screenshot(path: str = Field(default="", description="Save path (.png). Empty = temp dir.")) -> str:
    """Capture the active window to a PNG file and return its path, so the AI
    client (if it supports images) can actually see the screen."""
    import os
    import time
    from mio_cua.automation.windows import get_active_window_rect
    from mio_cua.vision.screen import capture_rect
    img = capture_rect(get_active_window_rect())
    if not path:
        tmp = os.path.join(os.environ.get("TEMP", "."), "mio_cua")
        os.makedirs(tmp, exist_ok=True)
        path = os.path.join(tmp, f"shot_{int(time.time()*1000)}.png")
    img.save(path)
    return f"saved screenshot to {path} ({img.size[0]}x{img.size[1]})"


@mcp.tool(name="mio_analyze_page", annotations={
    "title": "Perceive a web page as structured elements (pure vision)", "readOnlyHint": True,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_analyze_page(max_elements: int = Field(default=50, description="Max elements to return", ge=1, le=200)) -> str:
    """Parse the active window's screenshot into interactive page elements
    (buttons, links, inputs, text) WITHOUT needing a DOM/extension -- pure
    vision (OmniParser). Returns semantic label + screen bbox per element so a
    client can click precise coordinates. Best for web pages / browser UIs."""
    from mio_cua.automation.windows import get_active_window_rect
    from mio_cua.vision.screen import capture_rect
    from mio_cua.scene import omniparser
    img = capture_rect(get_active_window_rect())
    if img is None or img.size[0] < 2:
        return "Error: could not capture the active window"
    # Warm-up hint: if the parser is still cold-loading in the background,
    # this first call blocks on model load (10-20s on first run). Subsequent
    # calls are instant once cached.
    if omniparser._parser is None:
        return ("(OmniParser still loading the vision model on first use; "
                "call again in a few seconds for a fast parse)")
    nodes = omniparser.parse(img)
    if not nodes:
        return "(no interactive elements detected -- is OmniParser available? " \
               "env OMNIPARSER_DIR must point at the weights)"
    w, h = img.size
    # actionable (interactive) elements first, then text
    nodes.sort(key=lambda n: (0 if n.role == "button" else 1, n.bbox[1], n.bbox[0]))
    lines = [f"parsed {len(nodes)} elements (pure vision, no DOM)"]
    for n in nodes[:max_elements]:
        kind = "button" if n.role == "button" else "text"
        x, y, bw, bh = n.bbox
        label = (n.semantic or "").strip()
        # convert bbox (x,y,w,h) to (x0,y0,x1,y1) for clickability
        lines.append(f"- {label!r} [{kind}] x0={x} y0={y} x1={x+bw} y1={y+bh} conf={n.confidence:.2f}")
    if len(nodes) > max_elements:
        lines.append(f"... and {len(nodes) - max_elements} more")
    return "\n".join(lines)


@mcp.tool(name="mio_ocr_text", annotations={
    "title": "Read all text on the active window", "readOnlyHint": True,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_ocr_text(max_items: int = Field(default=80, description="Max text items", ge=1, le=300)) -> str:
    """OCR the active window and return the visible text with coordinates.
    Handy for reading dialogs, web pages and terminals the scene graph missed."""
    try:
        from mio_cua.automation.windows import get_active_window_rect
        from mio_cua.vision.screen import capture_rect
        from mio_cua.vision.ocr import get_elements
        img = capture_rect(get_active_window_rect())
        els = get_elements(img)
        lines = []
        for e in els[:max_items]:
            t = (e.text or "").strip()
            if t:
                lines.append(f"{t!r} bbox={e.bbox}")
        if not lines:
            return "(no text detected)"
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Navigation & window-management tools
# ---------------------------------------------------------------------------

@mcp.tool(name="mio_get_cursor", annotations={
    "title": "Get current mouse position", "readOnlyHint": True,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_get_cursor() -> str:
    """Return the current mouse (x, y) coordinates in screen pixels."""
    try:
        from mio_cua.automation.windows import get_cursor
        x, y = get_cursor()
        return f"cursor at ({x}, {y})"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool(name="mio_move_mouse", annotations={
    "title": "Move the mouse without clicking", "readOnlyHint": False,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_move_mouse(x: int = Field(..., description="Screen X coordinate"),
                         y: int = Field(..., description="Screen Y coordinate")) -> str:
    """Move the mouse to (x, y) without clicking. Use before a click when you
    need a hover first (tooltips, menus that react to hover)."""
    from mio_cua.automation.input_controller import InputController
    from mio_cua.models.action import Action
    ctrl = InputController()
    r = ctrl.execute(Action(id="mcp", type="move_mouse", params={"x": x, "y": y}))
    return "moved" if r.sent else f"Error: {r.error}"


@mcp.tool(name="mio_scroll", annotations={
    "title": "Scroll the active window", "readOnlyHint": False,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_scroll(amount: int = Field(default=3, description="Wheel clicks; positive=down, negative=up", ge=-50, le=50)) -> str:
    """Scroll the active window vertically, e.g. to read a long web page or
    document. Positive amount scrolls down, negative scrolls up."""
    if amount == 0:
        return "no scroll"
    from mio_cua.automation.input_controller import InputController
    from mio_cua.models.action import Action
    ctrl = InputController()
    r = ctrl.execute(Action(id="mcp", type="scroll",
                            params={"amount": abs(amount),
                                    "direction": "down" if amount > 0 else "up"}))
    return "scrolled" if r.sent else f"Error: {r.error}"


@mcp.tool(name="mio_list_windows", annotations={
    "title": "List all visible windows", "readOnlyHint": True,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_list_windows(max_windows: int = Field(default=40, description="Max windows to list", ge=1, le=200)) -> str:
    """List titles of all visible top-level windows. Use to find which window
    to focus next, or to confirm a window actually opened."""
    try:
        from mio_cua.automation.windows import _top_level_windows, _window_text
        titles = []
        for hwnd in _top_level_windows():
            t = _window_text(hwnd).strip()
            if t:
                titles.append(t)
        if not titles:
            return "(no visible windows)"
        lines = [f"found {len(titles)} windows"]
        for t in titles[:max_windows]:
            lines.append(f"- {t}")
        if len(titles) > max_windows:
            lines.append(f"... and {len(titles) - max_windows} more")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool(name="mio_close_window", annotations={
    "title": "Close a window by its title", "readOnlyHint": False,
    "destructiveHint": True, "idempotentHint": False, "openWorldHint": True,
})
async def mio_close_window(title: str = Field(..., description="Window title (or substring) to close")) -> str:
    """Close the window whose title contains the given text. Safe if the window
    has unsaved changes, the app will prompt (text lost only if you then type
    confirm). Prefer for apps that respond to a close click."""
    if not _confirm_mcp_tool("mio_close_window", {"title": title}):
        return "Rejected by user: mio_close_window"
    try:
        from mio_cua.automation.windows import _top_level_windows, _window_text
        import ctypes
        import ctypes.wintypes as wt
        user32 = ctypes.windll.user32
        user32.PostMessageW.restype = wt.BOOL
        user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        for hwnd in _top_level_windows():
            if title.lower() in _window_text(hwnd).lower():
                # WM_CLOSE asks the app to close gracefully (vs terminate)
                user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                return f"sent close to '{_window_text(hwnd)}'"
        return f"no window found with title containing '{title}'"
    except Exception as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Process & system-info tools
# ---------------------------------------------------------------------------

@mcp.tool(name="mio_list_processes", annotations={
    "title": "List running processes", "readOnlyHint": True,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_list_processes(pattern: str = Field(default="", description="Optional substring filter (e.g. 'chrome')"),
                             max_items: int = Field(default=40, description="Max processes to list", ge=1, le=200)) -> str:
    """List running processes (pid, name, memory). Use to find what's running
    before killing, or to confirm an app started."""
    try:
        import psutil
        rows = []
        for p in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                name = p.info.get("name") or "?"
                if pattern and pattern.lower() not in name.lower():
                    continue
                mem = p.info.get("memory_info")
                mb = (mem.rss / 1048576) if mem else 0
                rows.append(f"pid={p.info.get('pid')} {name} ({mb:.0f}MB)")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        rows.sort(key=lambda r: r.lower())
        if not rows:
            return f"(no processes matching '{pattern}')"
        lines = [f"found {len(rows)} processes"]
        lines += rows[:max_items]
        if len(rows) > max_items:
            lines.append(f"... and {len(rows) - max_items} more")
        return "\n".join(lines)
    except ImportError:
        return "Error: psutil not installed (pip install psutil)"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool(name="mio_kill_process", annotations={
    "title": "End a running process", "readOnlyHint": False,
    "destructiveHint": True, "idempotentHint": False, "openWorldHint": True,
})
async def mio_kill_process(name: str = Field(default="", description="Process name to kill (e.g. 'notepad', or full 'notepad.exe')"),
                           pid: int = Field(default=0, description="PID to kill (alternative to name)"),
                           force: bool = Field(default=False, description="True = terminate immediately, False = ask app to close first")) -> str:
    """End a process by name or PID. Prefer closing windows via mio_close_window
    first (lets the app save); use this for hung apps or headless processes."""
    if not _confirm_mcp_tool("mio_kill_process",
                             {"name": name, "pid": pid, "force": force}):
        return "Rejected by user: mio_kill_process"
    import subprocess
    target = pid if pid else name
    if not target:
        return "Error: provide a name or pid"
    try:
        if pid:
            subprocess.run(["taskkill", "/PID", str(pid), *(["/F"] if force else [])],
                           check=True, capture_output=True, text=True)
            return f"killed pid {pid}"
        proc = name if name.lower().endswith(".exe") else name + ".exe"
        subprocess.run(["taskkill", "/IM", proc, *(["/F"] if force else [])],
                       check=True, capture_output=True, text=True)
        return f"killed {proc}"
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr.strip() or e}"


@mcp.tool(name="mio_get_screen_info", annotations={
    "title": "Get monitor layout and DPI", "readOnlyHint": True,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_get_screen_info() -> str:
    """Return monitor resolution(s), layout (multi-monitor coordinates) and DPI
    scale. Use to reason about screen coordinates before clicking."""
    try:
        import win32api
        import win32con
        monitors = win32api.EnumDisplayMonitors()
        if not monitors:
            return "(no monitors detected)"
        lines = [f"{len(monitors)} monitor(s)"]
        for (hmon, hdc, rect) in monitors:
            info = win32api.GetMonitorInfo(hmon)
            work = info.get("Work") or info.get("rcWork") or info.get("Monitor")
            # DPI for this monitor's origin
            scale = 1.0
            try:
                import ctypes
                dpi_x, dpi_y = ctypes.c_uint(), ctypes.c_uint()
                ctypes.windll.shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
                scale = dpi_x.value / 96.0
            except Exception:
                pass
            primary = " (primary)" if (info.get("Flags", 0) & 1) else ""
            l, t, r, b = rect
            lines.append(f"- rect=({l},{t},{r},{b}) {r-l}x{b-t}px scale={scale:.2f}{primary}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool(name="mio_drag", annotations={
    "title": "Drag the mouse from A to B", "readOnlyHint": False,
    "destructiveHint": False, "idempotentHint": False, "openWorldHint": True,
})
async def mio_drag(x1: int = Field(..., description="Start X"), y1: int = Field(..., description="Start Y"),
                   x2: int = Field(..., description="End X"), y2: int = Field(..., description="End Y")) -> str:
    """Press left button at (x1,y1), drag to (x2,y2), release. For moving
    window/file icons, selecting ranges, or sliders."""
    from mio_cua.tools.drag import drag
    from mio_cua.automation.input_controller import InputController
    ctrl = InputController()
    ctrl.current_observation = _mcp_observe()
    ctx = _StubCtx()
    ctx.controller = ctrl
    ctx.current_observation = ctrl.current_observation
    res = drag(ctx, x1=x1, y1=y1, x2=x2, y2=y2)
    return res.message if res.success else f"Error: {res.message}"


def _mcp_observe():
    """Fresh observation for MCP tools that resolve element_id."""
    from mio_cua.perception import Perception
    return Perception().observe()


@mcp.tool(name="mio_select_element", annotations={
    "title": "Select an element's text", "readOnlyHint": False,
    "destructiveHint": False, "idempotentHint": False, "openWorldHint": True,
})
async def mio_select_element(element_id: int = Field(..., description="Element id to select (from mio_observe_scene)")) -> str:
    """Select an element's text by dragging across its bbox (single-line text).
    Caller then presses ctrl+c and verifies with mio_clipboard_get."""
    from mio_cua.tools.selection import select_element
    from mio_cua.automation.input_controller import InputController
    ctrl = InputController()
    ctrl.current_observation = _mcp_observe()
    ctx = _StubCtx()
    ctx.controller = ctrl
    ctx.current_observation = ctrl.current_observation
    res = select_element(ctx, element_id=element_id)
    return res.message if res.success else f"Error: {res.message}"


@mcp.tool(name="mio_sleep", annotations={
    "title": "Wait (no-op sleep)", "readOnlyHint": True,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_sleep(seconds: float = Field(default=1.0, description="Seconds to wait", ge=0.1, le=120)) -> str:
    """Do nothing for N seconds. Use between launch/wait steps while an app
    loads, or before checking a window that appears asynchronously."""
    time.sleep(seconds)
    return f"waited {seconds}s"


@mcp.tool(name="mio_vdesk", annotations={
    "title": "Run in an isolated virtual desktop", "readOnlyHint": False,
    "destructiveHint": False, "idempotentHint": False, "openWorldHint": True,
})
async def mio_vdesk(action: str = Field(..., description="'ensure' (create & switch to an isolated desktop), 'close' (close current desktop), 'left'/'right' (switch desktop)"),
                    number: int = Field(default=0, description="Desktop number to switch to (1-based, with action='num')")) -> str:
    """Control Windows virtual desktops so automation can run on an ISOLATED
    desktop without disturbing the user's main screen. Use 'ensure' first,
    run your clicks/typing, then 'close' to return to the main desktop."""
    import importlib.util
    import os
    v_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "vdesk.py")
    if not os.path.isfile(v_path):
        return "Error: scripts/vdesk.py not found"
    spec = importlib.util.spec_from_file_location("_mio_vdesk", v_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    a = action.lower()
    try:
        if a == "ensure":
            f = getattr(mod, "ensure_test_desktop", None) or mod.new_desktop
            f()
        elif a == "close":
            mod.close_desktop()
        elif a == "left":
            mod.switch_left()
        elif a == "right":
            mod.switch_right()
        elif a == "num":
            mod.switch_to(number)
        else:
            return f"Error: unknown action '{action}' (ensure/close/left/right/num)"
        return f"vdesk {a}: done"
    except Exception as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Clipboard & notification tools
# ---------------------------------------------------------------------------

@mcp.tool(name="mio_clipboard_get", annotations={
    "title": "Read the clipboard text", "readOnlyHint": True,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_clipboard_get() -> str:
    """Return the current clipboard text as structured JSON {text,has_text,length}."""
    from mio_cua.tools.clipboard import clipboard_get
    return _run(clipboard_get)


@mcp.tool(name="mio_clipboard_set", annotations={
    "title": "Set the clipboard text", "readOnlyHint": False,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_clipboard_set(text: str = Field(..., description="Text to place on the clipboard")) -> str:
    """Put text on the clipboard. Combine with a ctrl+v to paste without typing."""
    from mio_cua.tools.clipboard import clipboard_set
    return _run(clipboard_set, text=text)


@mcp.tool(name="mio_notify", annotations={
    "title": "Show a desktop notification", "readOnlyHint": True,
    "destructiveHint": False, "idempotentHint": True, "openWorldHint": True,
})
async def mio_notify(title: str = Field(..., description="Notification title"),
                     message: str = Field(default="", description="Notification message body")) -> str:
    """Show a Windows toast notification on the desktop (e.g. to alert the user
    that a long-running task finished)."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBeep(0)
        ctypes.windll.user32.MessageBoxW(0, (message or "done"), title, 0)
        return "notification sent"
    except Exception as e:
        return f"Error: {e}"


def main():
    """Entry point for `mio-cua-mcp` console script (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
