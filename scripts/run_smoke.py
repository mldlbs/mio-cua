"""Release-gate smoke tests: run the three acceptance scenarios against the live desktop.

Usage:
    python scripts/run_smoke.py                    # run all scenarios
    python scripts/run_smoke.py --only notepad     # run a subset (comma-separated ids)
    python scripts/run_smoke.py --dry-run          # list scenarios, no real input

The agent will REALLY move the mouse and type on your desktop. Press F9 at any
time to abort the current run.
"""
import argparse
import os
import sys
import time

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SMOKE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "smoke")


def _load_scenarios(only=None):
    scenarios = []
    for name in sorted(os.listdir(SMOKE_DIR)):
        if not name.endswith(".yaml"):
            continue
        with open(os.path.join(SMOKE_DIR, name), "r", encoding="utf8") as f:
            data = yaml.safe_load(f)
        if only and data["id"] not in only:
            continue
        scenarios.append(data)
    return scenarios


def _active_window():
    import win32gui
    return win32gui.GetWindowText(win32gui.GetForegroundWindow())


def _resolve_path(path: str) -> str:
    if path == "~/Desktop" or path.startswith("~/Desktop/"):
        desktop = _desktop_dir()
        rest = path[len("~/Desktop"):].lstrip("/\\")
        return os.path.join(desktop, rest) if rest else desktop
    return os.path.expanduser(path)


def _desktop_dir():
    try:
        import win32com.client
        return win32com.client.Dispatch("Shell.Application").NameSpace(0).Self.Path
    except Exception:
        return os.path.expanduser("~/Desktop")


def _check(rule):
    kind = rule["type"]
    if kind == "active_window":
        return rule["contains"] in _active_window()
    path = _resolve_path(rule["path"])
    if kind == "file_exists":
        return os.path.isfile(path)
    if kind == "dir_exists":
        return os.path.isdir(path)
    if kind == "file_contains":
        if not os.path.isfile(path):
            return False
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return rule["contains"] in f.read()
        except Exception:
            return False
    return False


def _run_scenario(scn, provider, model, base_url):
    from mio_cua import Agent, AgentConfig, Task
    from mio_cua.events import ActionStarted, TaskFinished

    cfg = AgentConfig(
        provider=provider,
        model=model,
        base_url=base_url or None,
        max_steps=scn["max_steps"],
        task_timeout_s=scn["timeout_s"],
    )
    agent = Agent(cfg)
    agent.events.subscribe(ActionStarted, lambda e: print(f"    [action] {e.action.type} {dict(e.action.params)}"))

    result = agent.run(Task(instruction=scn["instruction"]))
    print(f"    [result] status={result.status} steps={result.steps} summary={result.summary!r}")

    passed = result.status == "SUCCESS"
    notes = []
    artifact_checks = []
    for rule in scn.get("checks", []):
        ok = _check(rule)
        notes.append(f"{rule['type']}={ok}")
        if rule["type"] in ("file_exists", "dir_exists", "file_contains"):
            artifact_checks.append(ok)
    # A scenario with artifact checks only PASSES if BOTH the agent reported
    # success AND every artifact exists -- a premature success() that claims a
    # file/folder which does not exist must fail, not pass on status alone.
    if artifact_checks:
        passed = passed and all(artifact_checks)
    return passed, result.status, result.steps, result.duration, "; ".join(notes)


# Apps safe to force-kill between scenarios. NOT browsers -- msedge/chrome
# share processes with the user's real windows and closing them would lose tabs.
_SMOKE_APPS = ("notepad", "calc", "calculatorapp", "mspaint")


def _kill_stale_apps():
    """Close apps a previous scenario left open.

    Scenarios run back-to-back on the same desktop; a leftover calculator
    window gets reused by the next scenario and the agent starts clicking it
    instead of following the new task.
    """
    try:
        import subprocess
        for app in _SMOKE_APPS:
            subprocess.run(
                ["taskkill", "/F", "/IM", f"{app}.exe"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="comma-separated scenario ids")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--provider", default=os.environ.get("mio_cua_PROVIDER", "openai"))
    parser.add_argument("--model", default=os.environ.get("mio_cua_MODEL", "gpt-4o"))
    parser.add_argument("--base-url", default=os.environ.get("mio_cua_BASE_URL", ""))
    args = parser.parse_args()

    only = set(args.only.split(",")) if args.only else None
    scenarios = _load_scenarios(only)
    if not scenarios:
        print("no scenarios to run")
        return 1

    if args.dry_run:
        for scn in scenarios:
            print(f"[{scn['id']}] {scn['title']}")
            print(f"    {scn['instruction']}")
            for rule in scn.get("checks", []):
                print(f"    check: {rule['type']} {rule.get('contains') or rule.get('path')}")
        return 0

    print("WARNING: this will move your mouse and type on the real desktop. Press F9 to abort.")
    for i in range(3, 0, -1):
        print(f"starting in {i}...")
        time.sleep(1)

    results = []
    for scn in scenarios:
        print(f"\n=== [{scn['id']}] {scn['title']} ===")
        _kill_stale_apps()
        try:
            results.append((scn["id"], *_run_scenario(scn, args.provider, args.model, args.base_url)))
        except Exception as e:
            print(f"    ERROR: {e}")
            results.append((scn["id"], False, "ERROR", 0, 0, str(e)))

    print("\n=== SUMMARY ===")
    all_ok = True
    for rid, passed, status, steps, dur, notes in results:
        flag = "PASS" if passed else "FAIL"
        all_ok = all_ok and passed
        print(f"[{flag}] {rid} status={status} steps={steps} {dur:.1f}s {notes}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
