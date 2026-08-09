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


def main():
    """Entry point for `mio-cua-mcp` console script (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
