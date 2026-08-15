"""High-risk tool registry: tools that need user confirmation before running."""

HIGH_RISK = {
    "delete": "Delete a file/folder (irreversible)",
    "overwrite": "Overwrite an existing file",
    "kill_process": "End a running process",
    "close_window": "Close a window (may lose unsaved work)",
}


def is_high_risk(tool_name) -> bool:
    """True if the tool needs user confirmation before running."""
    return bool(tool_name) and tool_name in HIGH_RISK
