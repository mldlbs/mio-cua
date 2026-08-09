"""Filesystem tools: create directories and move files.

These let the agent organize the desktop (or any folder) directly through the
filesystem, instead of fragile click-and-drag on the Explorer UI. The agent
decides *what* goes *where* (classification); the tools do the move reliably.
"""

import os
import shutil

from mio_cua.models.action_result import ActionResult


def list_dir(ctx, path=None):
    """List files and directories under ``path`` (one per line, files first).

    Used to inventory a folder (e.g. the desktop) before organizing it.
    """
    if not path:
        return ActionResult(ctx.current_action_id, False, "path required", retryable=True)
    try:
        entries = os.listdir(path)
        entries.sort(key=lambda n: (os.path.isdir(os.path.join(path, n)), n.lower()))
        return ActionResult(ctx.current_action_id, True, "\n".join(entries))
    except Exception as e:
        return ActionResult(ctx.current_action_id, False, str(e), retryable=True)


def make_dir(ctx, path=None):
    """Create a directory (recursively) if it does not exist."""
    if not path:
        return ActionResult(ctx.current_action_id, False, "path required", retryable=True)
    try:
        os.makedirs(path, exist_ok=True)
        return ActionResult(ctx.current_action_id, True, f"created {path}")
    except Exception as e:
        return ActionResult(ctx.current_action_id, False, str(e), retryable=True)


def move_file(ctx, src=None, dest=None):
    """Move ``src`` into directory ``dest`` (created if needed), keeping its name.

    ``dest`` is ALWAYS a directory. Refuses to overwrite an existing file.
    """
    if not src or not dest:
        return ActionResult(ctx.current_action_id, False, "src and dest required", retryable=True)
    if not os.path.isfile(src):
        return ActionResult(ctx.current_action_id, False, f"source not found: {src}", retryable=True)
    try:
        os.makedirs(dest, exist_ok=True)
        target = os.path.join(dest, os.path.basename(src))
        if os.path.exists(target):
            return ActionResult(ctx.current_action_id, False, f"refusing to overwrite: {target}", retryable=False)
        shutil.move(src, target)
        return ActionResult(ctx.current_action_id, True, f"moved {src} -> {target}")
    except Exception as e:
        return ActionResult(ctx.current_action_id, False, str(e), retryable=True)


def move_files(ctx, files=None, dest=None):
    """Move a LIST of files into one directory ``dest`` (created if needed).

    More efficient than move_file per file when organizing many files: one
    call moves them all and reports each result. Refuses to overwrite.
    """
    if not files or not dest:
        return ActionResult(ctx.current_action_id, False, "files (list) and dest required", retryable=True)
    if not isinstance(files, list):
        return ActionResult(ctx.current_action_id, False, "files must be a list of paths", retryable=True)
    try:
        os.makedirs(dest, exist_ok=True)
        results = []
        moved = 0
        for src in files:
            if not os.path.isfile(src):
                results.append(f"SKIP {os.path.basename(src)} (not found)")
                continue
            target = os.path.join(dest, os.path.basename(src))
            if os.path.exists(target):
                results.append(f"SKIP {os.path.basename(src)} (exists)")
                continue
            shutil.move(src, target)
            moved += 1
            results.append(f"moved {os.path.basename(src)}")
        msg = f"moved {moved} files into {dest}:\n" + "\n".join(results)
        return ActionResult(ctx.current_action_id, moved > 0, msg, retryable=False)
    except Exception as e:
        return ActionResult(ctx.current_action_id, False, str(e), retryable=True)
