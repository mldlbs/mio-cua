"""Metric computation for benchmark run results.

Goal Progress Rate is intentionally NOT computed here: it requires the
Progress Model, which is a later Agent Runtime v2 milestone. The metrics
below are derivable from current observational signals only.
"""

import statistics
from typing import Any, Dict, List

from mio_cua.evaluation.harness import RunResult


def compute_metrics(results: List[RunResult]) -> Dict[str, Any]:
    total = len(results)
    if total == 0:
        return {}

    success = [r for r in results if r.status == "SUCCESS"]
    timeout = [r for r in results if r.status == "TIMEOUT"]
    fail = [r for r in results if r.status in ("FAIL", "ABORTED", "ERROR")]

    total_actions = sum(r.steps for r in results)
    total_cv = sum(r.context_violations for r in results)
    total_tv = sum(r.target_violations for r in results)
    total_ss = sum(r.scroll_stalls for r in results)
    total_rec = sum(r.recoveries for r in results)
    steps_list = [r.steps for r in results]
    durations = [r.duration for r in results]

    evidence_complete = 0
    if success:
        evidence_complete = sum(1 for r in success if r.artifacts > 0) / len(success)

    return {
        "total_tasks": total,
        "task_success_rate": round(len(success) / total, 3),
        "timeout_rate": round(len(timeout) / total, 3),
        "fail_rate": round(len(fail) / total, 3),
        "avg_steps": round(statistics.mean(steps_list), 2),
        "median_steps": statistics.median(steps_list),
        "max_steps": max(steps_list),
        "total_context_violations": total_cv,
        "total_target_violations": total_tv,
        "total_scroll_stalls": total_ss,
        "total_recoveries": total_rec,
        "context_violation_per_task": round(total_cv / total, 3),
        "target_violation_per_task": round(total_tv / total, 3),
        "wrong_action_rate": round((total_cv + total_tv) / total_actions, 3) if total_actions else 0.0,
        "scroll_stall_per_task": round(total_ss / total, 3),
        "evidence_completeness": round(evidence_complete, 3),
        "avg_duration_s": round(statistics.mean(durations), 2),
    }


def render_report(
    results: List[RunResult], metrics: Dict[str, Any]
) -> str:
    lines: List[str] = []
    lines.append("# mio-cua Benchmark Report")
    lines.append("")
    lines.append("## Per-task")
    lines.append("")
    lines.append("| Task | Status | Steps | CtxViol | TgtViol | ScrollStall | Recover | Artifacts | Duration |")
    lines.append("|------|--------|-------|--------|---------|-------------|---------|-----------|----------|")
    for r in results:
        lines.append(
            f"| {r.task_id} | {r.status} | {r.steps} | {r.context_violations} | "
            f"{r.target_violations} | {r.scroll_stalls} | {r.recoveries} | {r.artifacts} | {r.duration:.1f}s |"
        )
    lines.append("")
    lines.append("## Aggregate Metrics")
    lines.append("")
    for k, v in metrics.items():
        lines.append(f"- **{k}**: {v}")
    lines.append("")
    return "\n".join(lines)
