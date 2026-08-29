"""Benchmark CLI: run a dataset through the harness and emit a report.

Usage:
    python -m mio_cua.evaluation.benchmark \
        --dataset mio_cua/evaluation/benchmarks/wechat_10.json \
        --base-url https://ai.crlkcloud.cyou/v1 \
        --model default \
        --max-steps 15 --timeout 120 \
        --run-dir C:/Temp/mio_cua_bench \
        --limit 2
"""

import argparse
import json
import logging
import os
import sys

logger = logging.getLogger(__name__)


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="mio-cua benchmark runner")
    p.add_argument("--dataset", required=True, help="path to benchmark JSON")
    p.add_argument("--base-url", default="https://ai.crlkcloud.cyou/v1")
    p.add_argument("--api-key-env", default="MIO_API_KEY")
    p.add_argument("--api-key", default=None, help="override API key (else read from env)")
    p.add_argument("--model", default="default")
    p.add_argument("--max-steps", type=int, default=15)
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--run-dir", default="C:/Temp/mio_cua_bench")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--app", default=None)
    p.add_argument("--runtime-v2", action="store_true",
                   help="use Agent Runtime v2 (Belief/Progress/Recovery) instead of v1")
    p.add_argument("--tags", default=None, help="comma-separated tags")
    p.add_argument("--ids", default=None, help="comma-separated task ids")
    p.add_argument("--log", default="WARNING")
    return p


def main(argv=None) -> int:
    args = build_argparser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log.upper(), logging.WARNING))

    from mio_cua.config import AgentConfig
    from mio_cua.evaluation.dataset import TaskDataset
    from mio_cua.evaluation.harness import Harness
    from mio_cua.evaluation.metrics import compute_metrics, render_report

    api_key = args.api_key or os.environ.get(args.api_key_env, "")

    config = AgentConfig(
        base_url=args.base_url,
        api_key_env=args.api_key_env,
        model=args.model,
        max_steps=args.max_steps,
        task_timeout_s=args.timeout,
        artifact_dir=os.path.join(args.run_dir, "artifacts"),
        runtime_v2=args.runtime_v2,
    )

    dataset = TaskDataset.load(args.dataset)
    tags = args.tags.split(",") if args.tags else None
    ids = args.ids.split(",") if args.ids else None
    tasks = dataset.filter(app=args.app, tags=tags, ids=ids, limit=args.limit)
    if not tasks:
        print("No tasks matched the filter.", file=sys.stderr)
        return 2

    print(f"Loaded dataset '{dataset.name}' ({len(dataset.tasks)} tasks); running {len(tasks)}.")

    harness = Harness(
        config, run_dir=args.run_dir, api_key=api_key, api_key_env=args.api_key_env
    )
    results = harness.run_all(tasks)
    metrics = compute_metrics(results)

    report = render_report(results, metrics)
    print("\n" + report)

    os.makedirs(args.run_dir, exist_ok=True)
    with open(os.path.join(args.run_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(report)
    with open(os.path.join(args.run_dir, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    with open(os.path.join(args.run_dir, "runs.json"), "w", encoding="utf-8") as f:
        json.dump([r.to_dict() for r in results], f, ensure_ascii=False, indent=2)
    print(f"\nSaved report to {args.run_dir}/report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ===========================================================================
# Phase 3 — Benchmark aggregation over recorded traces (spec §26-§27)
# ===========================================================================

def benchmark(traces: list) -> "Any":
    """Aggregate a list of ``schema.Trace`` into a ``BenchmarkResult``.

    Computes (spec §27):
      * Task Success Rate      = successful tasks / total tasks
      * Step Success Rate      = successful actions / total actions
      * Failure Distribution   = count per failure category
      * Recovery Success Rate  = successful recoveries / recovery attempts
      * Average Steps / Average Recovery Count
    """
    from collections import Counter

    from mio_cua.evaluation.schema import BenchmarkResult, EventType

    total = len(traces)
    if total == 0:
        return BenchmarkResult()

    success = 0
    failed = 0
    dist = Counter()
    recovery_attempts = 0
    recovery_success = 0
    steps_total = 0
    actions_total = 0
    actions_success = 0

    for t in traces:
        ok = t.success
        if ok:
            success += 1
        else:
            failed += 1

        if t.failure is not None:
            dist[t.failure.category] += 1
        elif not ok:
            dist["unknown"] += 1

        # Step / action success rate.
        for ev in t.events:
            if ev.event_type == "action_completed":
                actions_total += 1
                act = (ev.payload or {}).get("action") or {}
                if act.get("success"):
                    actions_success += 1

        # Recovery accounting.
        rec_completed = t.events_of(EventType.RECOVERY_COMPLETED.value)
        recovery_attempts += len(rec_completed)
        for ev in rec_completed:
            rec = (ev.payload or {}).get("recovery") or {}
            if rec.get("success"):
                recovery_success += 1

        steps_total += t.steps

    recovery_rate = (recovery_success / recovery_attempts) if recovery_attempts else 0.0
    step_rate = (actions_success / actions_total) if actions_total else 0.0

    return BenchmarkResult(
        total_tasks=total,
        success_tasks=success,
        failed_tasks=failed,
        success_rate=round(success / total, 4),
        failure_distribution=dict(dist),
        recovery_success_rate=round(recovery_rate, 4),
        average_steps=round(steps_total / total, 3),
        average_recovery_count=round(recovery_attempts / total, 3),
        metadata={"step_success_rate": round(step_rate, 4)},
    )
