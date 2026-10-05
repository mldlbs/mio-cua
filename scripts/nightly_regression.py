"""Nightly smoke regression: run the core acceptance scenarios on the dedicated
test desktop, collect per-scenario results, write a report, and return to the
main desktop. Intended to run unattended (Windows Task Scheduler at night).

    python scripts/nightly_regression.py [--only id,id] [--report <path>]

Reads the DeepSeek key from D:\\Users\\gf1913\\.mio-cua-secrets\\tokens.json so no
secret lives in the scheduler command. Returns exit code 0 only if all chosen
scenarios passed. Safe for the user's work day: everything runs on desktop #2
and control returns to desktop #1 at the end.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SMOKE_RUNNER = os.path.join(HERE, "run_smoke.py")
SECRETS = r"D:\Users\gf1913\.mio-cua-secrets\tokens.json"
DEFAULT_DESKTOP = os.path.join(os.environ.get("USERPROFILE", "C:\\"), "Desktop")
REPORT = os.path.join(os.environ.get("USERPROFILE", "C:\\"), "Desktop", "smoke_nightly_report.txt")

# 5 core acceptance scenarios; --only can override.
CORE = ["calculator", "crossapp", "explorer", "notepad", "web"]


def _secrets():
    with open(SECRETS, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _run_one(scn_id, base_url, model, log_dir):
    logf = os.path.join(log_dir, f"smoke_nightly_{scn_id}.log")
    t0 = time.time()
    cmd = [
        sys.executable, SMOKE_RUNNER,
        "--only", scn_id,
        "--model", model,
        "--base-url", base_url,
    ]
    with open(logf, "w", encoding="utf-8", errors="replace") as lf:
        try:
            proc = subprocess.run(
                cmd, cwd=ROOT,
                stdout=lf, stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                timeout=60 * 25,  # generous per-scenario ceiling
            )
            ok = proc.returncode == 0
        except subprocess.TimeoutExpired:
            ok = False
            lf.write("\n[nightly] TIMED OUT\n")
    return ok, time.time() - t0, logf


def main():
    import vdesk  # noqa: F401  (scripts dir on path)

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", default=",".join(CORE), help="comma-separated scenario ids")
    ap.add_argument("--report", default=REPORT)
    ap.add_argument("--model", default="deepseek-v4-flash")
    ap.add_argument("--base-url", default="https://api.deepseek.com/v1")
    args = ap.parse_args()

    chosen = [s.strip() for s in args.only.split(",") if s.strip()]

    secrets = _secrets()
    os.environ["OPENAI_API_KEY"] = secrets.get("api_key") or secrets.get("openai") or ""
    if not os.environ.get("OPENAI_API_KEY"):
        print("FATAL: no api key in secrets file", file=sys.stderr)
        return 2

    log_dir = os.path.join(os.environ.get("TEMP", "."), "mio_nightly")
    os.makedirs(log_dir, exist_ok=True)

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"mio-cua nightly regression {stamp}", "=" * 40]

    # isolate on the test desktop
    vdesk.ensure_test_desktop()
    time.sleep(2)
    lines.append(f"test desktop engaged, running {len(chosen)} scenario(s)...")

    results = []
    for scn_id in chosen:
        ok, dur, logf = _run_one(scn_id, args.base_url, args.model, log_dir)
        results.append((scn_id, ok, dur))
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {scn_id} {dur:.0f}s  -> {logf}")

    # back to the user's desktop
    try:
        vdesk.switch_to(1)
    except Exception:
        pass
    lines.append("returned to desktop #1")

    passed = sum(1 for _, ok, _ in results if ok)
    lines.append(f"RESULT: {passed}/{len(results)} passed")
    report = "\n".join(lines) + "\n"
    with open(args.report, "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    return 0 if passed == len(results) and len(results) > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
