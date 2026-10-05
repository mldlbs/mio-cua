"""Real-desktop A/B/C/D sweep for the WeChat "搜索兴蓉打开聊天" task.

WHY THIS FILE EXISTS
--------------------
The user's hypothesis: the de-modeled layers (Grounding, Verification,
Recovery) add value ONLY if they raise real task success rate. This script
runs four progressively-augmented agent versions, 20 times each, on a REAL
desktop with WeChat open, and records the six metrics that decide the question:

    A  LLM + raw execution            (runtime_v1, no grounding/recovery/verify)
    B  A + Grounding                  (live re-resolve at click time)
    C  B + Verification               (batch in-step verification)
    D  C + Deterministic Recovery     (Esc / refocus / scroll-reverse)

METRICS
    task_success_rate            success / runs
    error_click_rate            blocked/void clicks / total clicks (from trajectory)
    target_localization_success click hits / total clicks (from trajectory)
    verification_false_positive failed runs that had a "verification success" event
    recovery_success_rate       recovery_completed(success) / recovery_completed
    avg_steps                   mean steps per run

IMPORTANT
    This MUST run on a machine with WeChat installed + a GUI + a valid
    OPENAI_API_KEY. The sandbox has no GUI, so it cannot produce the real
    numbers. Use ``--dry-run`` to print the matrix without executing.

USAGE
    python experiments/real_sweep.py --dry-run
    python experiments/real_sweep.py --runs 20 --task "微信中搜索兴蓉，打开正确的聊天"
"""

import argparse
import csv
import json
import os
import glob
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from mio_cua.agent_factory import Agent
from mio_cua.config import AgentConfig
from mio_cua.models.task import Task


# -- an event sink that just records what the loop emitted --------------
class CollectorSink:
    def __init__(self):
        self.events: List[dict] = []

    def emit(self, ev):
        try:
            self.events.append({"type": ev.event_type, "payload": ev.payload})
        except Exception:
            pass


# -- the four versions (progressive layer enablement) -------------------
VERSIONS = {
    "A_raw": {
        "runtime_v2": False,
        "enable_grounding": False,
        "enable_verification": False,
        "enable_recovery": False,
    },
    "B_grounding": {
        "runtime_v2": True,
        "enable_grounding": True,
        "enable_verification": False,
        "enable_recovery": False,
    },
    "C_verification": {
        "runtime_v2": True,
        "enable_grounding": True,
        "enable_verification": True,
        "enable_recovery": False,
    },
    "D_recovery": {
        "runtime_v2": True,
        "enable_grounding": True,
        "enable_verification": True,
        "enable_recovery": True,
    },
}


@dataclass
class RunMetrics:
    runs: int = 0
    success: int = 0
    steps_sum: int = 0
    clicks_total: int = 0
    clicks_hit: int = 0
    error_clicks: int = 0
    verify_fail_fp: int = 0   # failed run that had a verification-success event
    fail_runs: int = 0
    recovery_attempts: int = 0
    recovery_ok: int = 0

    def task_success_rate(self) -> Optional[float]:
        return self.success / self.runs if self.runs else None

    def error_click_rate(self) -> Optional[float]:
        return self.error_clicks / self.clicks_total if self.clicks_total else None

    def target_localization_success(self) -> Optional[float]:
        return self.clicks_hit / self.clicks_total if self.clicks_total else None

    def verification_false_positive_rate(self) -> Optional[float]:
        return self.verify_fail_fp / self.fail_runs if self.fail_runs else None

    def recovery_success_rate(self) -> Optional[float]:
        return self.recovery_ok / self.recovery_attempts if self.recovery_attempts else None

    def avg_steps(self) -> Optional[float]:
        return self.steps_sum / self.runs if self.runs else None


def _read_trajectory(state_dir: str, task_id: str) -> List[dict]:
    path = os.path.join(state_dir, f"trajectory_{task_id}.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _accumulate(m: RunMetrics, result, sink: CollectorSink, state_dir: str):
    m.runs += 1
    if result.status == "SUCCESS":
        m.success += 1
    else:
        m.fail_runs += 1
    m.steps_sum += result.steps

    traj = _read_trajectory(state_dir, result.task_id)
    for e in traj:
        if e.get("action") == "click":
            m.clicks_total += 1
            if e.get("result_success"):
                m.clicks_hit += 1
            if e.get("target_violated") or str(e.get("reason", "")).startswith("blocked"):
                m.error_clicks += 1

    # verification false-positive: run failed but a verification reported success
    had_verify_success = any(
        ev["type"] == "verification" and ev["payload"].get("verification", {}).get("success")
        for ev in sink.events
    )
    if result.status != "SUCCESS" and had_verify_success:
        m.verify_fail_fp += 1

    # recovery success
    for ev in sink.events:
        if ev["type"] == "recovery_completed":
            m.recovery_attempts += 1
            if ev["payload"].get("recovery", {}).get("success"):
                m.recovery_ok += 1


def run_version(name: str, overrides: dict, task: Task, runs: int, artifact_dir: str) -> RunMetrics:
    m = RunMetrics()
    state_dir = os.path.join(artifact_dir, "state")
    for i in range(runs):
        config = AgentConfig(artifact_dir=artifact_dir, **overrides)
        agent = Agent(config)
        sink = CollectorSink()
        print(f"  [{name}] run {i + 1}/{runs} ...", flush=True)
        result = agent.run(task, event_sinks=[sink], record=True)
        _accumulate(m, result, sink, state_dir)
    return m


def _fmt(v: Optional[float]) -> str:
    return f"{v:.3f}" if v is not None else "n/a"


def main():
    ap = argparse.ArgumentParser(description="Real-desktop A/B/C/D sweep")
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument(
        "--task",
        default="微信中搜索兴蓉，打开正确的聊天",
    )
    ap.add_argument("--artifact-dir", default=os.path.expanduser("~/.mio_cua/artifacts"))
    ap.add_argument("--dry-run", action="store_true",
                    help="print the version matrix and exit (no desktop needed)")
    args = ap.parse_args()

    task = Task(
        instruction=args.task,
        target_context={"app": "微信", "window": "微信", "keyword": "兴蓉"},
    )

    print("=" * 72)
    print("REAL-DESKTOP A/B/C/D SWEEP  —  WeChat: 搜索兴蓉打开聊天")
    print("=" * 72)
    print(f"task : {task.instruction}")
    print(f"runs : {args.runs}   (per version)")
    for name, ov in VERSIONS.items():
        print(f"  {name:14s} {ov}")
    print("metrics: task_success | error_click | target_loc | verify_fp | recovery | avg_steps")
    print("expected shape if layers help:  40% -> 55% -> 62% -> 75%")
    print("expected shape if they don't:   40% -> 42% -> 43% -> 44%")

    if args.dry_run:
        print("\n[dry-run] no execution. Run without --dry-run on a desktop with "
              "WeChat open and OPENAI_API_KEY set.")
        return

    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set. Aborting.", file=sys.stderr)
        sys.exit(2)
    print("\nMake sure WeChat is OPEN and focused-capable on this desktop.\n")

    rows = []
    for name, ov in VERSIONS.items():
        print(f"\n### version {name}")
        m = run_version(name, ov, task, args.runs, args.artifact_dir)
        rows.append({
            "version": name,
            "task_success_rate": _fmt(m.task_success_rate()),
            "error_click_rate": _fmt(m.error_click_rate()),
            "target_localization_success": _fmt(m.target_localization_success()),
            "verification_false_positive_rate": _fmt(m.verification_false_positive_rate()),
            "recovery_success_rate": _fmt(m.recovery_success_rate()),
            "avg_steps": _fmt(m.avg_steps()),
        })

    out_csv = os.path.join(os.path.dirname(__file__), "results", "real_sweep.csv")
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwritten: {out_csv}")
    print("\nRESULT")
    for r in rows:
        print(f"  {r['version']:14s} success={r['task_success_rate']:>5} "
              f"err_click={r['error_click_rate']:>5} loc={r['target_localization_success']:>5} "
              f"verify_fp={r['verification_false_positive_rate']:>5} "
              f"recovery={r['recovery_success_rate']:>5} steps={r['avg_steps']:>5}")


if __name__ == "__main__":
    main()
