"""Run the smoke test on a dedicated Win11 virtual desktop, isolated from the user.

Reuses ONE dedicated virtual desktop (desktop #2, marked by a hidden marker
window) instead of opening a new desktop every run -- so they don't pile up.
After the run, switch back to the main desktop with `python scripts/vdesk.py num 1`.
"""
import os
import subprocess
import sys
import time

import vdesk

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(os.environ.get("TEMP", "."), "smoke_vdesk.log")


def main():
    import argparse
    import win32gui

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default="notepad")
    parser.add_argument("--model", default=os.environ.get("mio_cua_MODEL", "deepseek-v4-flash"))
    parser.add_argument("--base-url", default=os.environ.get("mio_cua_BASE_URL", "https://api.deepseek.com/v1"))
    parser.add_argument("--log", default=LOG)
    args = parser.parse_args()

    vdesk.ensure_test_desktop()  # reuse desktop #2 instead of creating anew
    _kill_stale_apps()
    fg = win32gui.GetWindowText(win32gui.GetForegroundWindow())
    logf = open(args.log, "w", encoding="utf-8", errors="replace")
    print(f"foreground after switch: {fg!r}", file=logf, flush=True)
    if "OpenCode" in fg or "Code" in fg:
        print("WARNING: still on the main desktop; switching may have failed", file=logf, flush=True)
    cmd = [
        sys.executable, os.path.join(HERE, "run_smoke.py"),
        "--only", args.only,
        "--model", args.model,
        "--base-url", args.base_url,
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=os.path.dirname(HERE),
        stdout=logf,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    print(f"PID={proc.pid}", flush=True)
    print(f"log={args.log}", flush=True)
    print("reused the dedicated test desktop; smoke test is running there.")


def _kill_stale_apps():
    """Close apps a previous smoke run may have left on the test desktop."""
    for app in ("notepad", "calc", "calculatorapp", "mspaint", "msedge"):
        subprocess.run(
            ["taskkill", "/F", "/IM", f"{app}.exe"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


if __name__ == "__main__":
    main()
