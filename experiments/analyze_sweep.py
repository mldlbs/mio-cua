"""Read experiments/results/real_sweep.csv and turn it into a verdict.

WHY THIS FILE EXISTS
--------------------
real_sweep.py writes the raw per-version metrics. This analyzer answers the
question the sweep was built to answer:

    Did Grounding / Verification / Deterministic Recovery actually add value?

It does NOT invent numbers. It only reads the CSV that ``real_sweep.py``
produced on a REAL desktop and presents:

    1. the 6-metric table (A/B/C/D)
    2. per-layer incremental deltas (B-A, C-B, D-C) on task success
    3. a heuristic verdict against the user's two hypotheses:
         helps : 40% -> 55% -> 62% -> 75%
         no-op : 40% -> 42% -> 43% -> 44%

This is experiment tooling, NOT agent architecture. It never touches the agent.

USAGE
    python experiments/analyze_sweep.py --csv experiments/results/real_sweep.csv
    python experiments/analyze_sweep.py --selftest   # synthetic, no real numbers
"""

import argparse
import csv
import os
import sys

METRIC_KEYS = [
    "task_success_rate",
    "error_click_rate",
    "target_localization_success",
    "verification_false_positive_rate",
    "recovery_success_rate",
    "avg_steps",
]

ORDER = ["A_raw", "B_grounding", "C_verification", "D_recovery"]


def _f(v: str):
    """Parse a CSV cell: '0.400' -> 0.4, 'n/a' -> None."""
    if v is None:
        return None
    v = str(v).strip()
    if v == "" or v.lower() == "n/a":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def load_csv(path: str):
    if not os.path.exists(path):
        raise SystemExit(f"ERROR: CSV not found: {path}\n"
                         f"       Run real_sweep.py on a desktop with WeChat open first.")
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            row = {"version": r.get("version", "").strip()}
            for k in METRIC_KEYS:
                row[k] = _f(r.get(k))
            rows.append(row)
    # keep canonical order; unknown versions appended
    by_name = {r["version"]: r for r in rows}
    ordered = [by_name[n] for n in ORDER if n in by_name]
    ordered += [r for r in rows if r["version"] not in ORDER]
    return ordered


def _delta(a, b):
    if a is None or b is None:
        return None
    return b - a


def deltas(rows):
    out = []
    for i in range(1, len(rows)):
        prev, cur = rows[i - 1], rows[i]
        out.append({
            "from": prev["version"],
            "to": cur["version"],
            "task_success": _delta(prev["task_success_rate"], cur["task_success_rate"]),
            "localization": _delta(prev["target_localization_success"], cur["target_localization_success"]),
            "error_click": _delta(prev["error_click_rate"], cur["error_click_rate"]),
            "verify_fp": _delta(prev["verification_false_positive_rate"], cur["verification_false_positive_rate"]),
            "recovery": _delta(prev["recovery_success_rate"], cur["recovery_success_rate"]),
            "avg_steps": _delta(prev["avg_steps"], cur["avg_steps"]),
        })
    return out


def interpret(rows, dts):
    """Heuristic, clearly labeled as non-proof. Returns list of (label, finding)."""
    by = {r["version"]: r for r in rows}
    findings = []

    def g(name, key):
        return by.get(name, {}).get(key)

    # Grounding: B vs A. Value if success rose AND localization rose.
    a_s, b_s = g("A_raw", "task_success_rate"), g("B_grounding", "task_success_rate")
    a_l, b_l = g("A_raw", "target_localization_success"), g("B_grounding", "target_localization_success")
    if None not in (a_s, b_s, a_l, b_l):
        if b_s > a_s and b_l > a_l:
            findings.append(("Grounding", f"成功 {a_s:.0%}->{b_s:.0%} 且 定位 {a_l:.0%}->{b_l:.0%}：抗漂移有正向贡献"))
        elif b_s > a_s and b_l <= a_l:
            findings.append(("Grounding", f"成功 {a_s:.0%}->{b_s:.0%} 但 定位未升：贡献可能来自别处，需看轨迹"))
        else:
            findings.append(("Grounding", f"成功 {a_s:.0%}->{b_s:.0%}：未观察到正向贡献"))

    # Verification: C vs B. Helps if success rose while verify_fp is low;
    # harms/neutral if verify_fp is high (creating false success).
    c_s = g("C_verification", "task_success_rate")
    b_s_v = g("B_grounding", "task_success_rate")
    c_fp = g("C_verification", "verification_false_positive_rate")
    if None not in (b_s_v, c_s):
        if c_s > b_s_v and (c_fp is None or c_fp < 0.3):
            findings.append(("Verification", f"成功 {b_s_v:.0%}->{c_s:.0%} 且 误判率 {c_fp if c_fp is not None else 0:.0%}：帮忙而非制造假成功"))
        elif c_fp is not None and c_fp >= 0.5:
            findings.append(("Verification", f"误判率 {c_fp:.0%} 偏高：存在制造假成功风险，对照失败任务人工核验"))
        elif c_s <= b_s_v:
            findings.append(("Verification", f"成功 {b_s_v:.0%}->{c_s:.0%}：未观察到正向贡献"))

    # Recovery: D vs C. Value if success rose AND recovery_success_rate > 0.
    d_s = g("D_recovery", "task_success_rate")
    d_rec = g("D_recovery", "recovery_success_rate")
    if None not in (c_s, d_s):
        if d_s > c_s and (d_rec is None or d_rec > 0):
            findings.append(("Recovery", f"成功 {c_s:.0%}->{d_s:.0%} 且 恢复成功率 {d_rec if d_rec is not None else 0:.0%}：确定性恢复有正向贡献"))
        elif d_s <= c_s:
            findings.append(("Recovery", f"成功 {c_s:.0%}->{d_s:.0%}：未观察到正向贡献（规则可能仍太初级）"))

    return findings


def render(rows, dts, findings, source="csv"):
    lines = []
    lines.append("=" * 78)
    lines.append("REAL-DESKTOP SWEEP — ANALYSIS")
    lines.append(f"source: {source}")
    lines.append("=" * 78)
    hdr = f"{'version':14s} " + " ".join(f"{k.replace('_rate','').replace('task_success','succ').replace('target_localization_success','loc').replace('error_click','err').replace('verification_false_positive','vfp').replace('recovery_success','rec').replace('avg_steps','steps'):>7s}" for k in METRIC_KEYS)
    lines.append(hdr)
    for r in rows:
        cells = []
        for k in METRIC_KEYS:
            v = r.get(k)
            cell = f"{v:.3f}" if isinstance(v, float) else "n/a"
            cells.append(f"{cell:>7s}")
        lines.append(f"{r['version']:14s} " + " ".join(cells))
    lines.append("")
    lines.append("INCREMENTAL DELTAS (task success | localization | error_click):")
    for d in dts:
        def fmt(x):
            return f"{x:+.3f}" if isinstance(x, float) else "n/a"
        lines.append(f"  {d['from']:14s} -> {d['to']:14s}  "
                     f"succ={fmt(d['task_success'])}  loc={fmt(d['localization'])}  err={fmt(d['error_click'])}")
    lines.append("")
    lines.append("LAYER VERDICT (heuristic, not proof — confirm against trajectories):")
    for label, finding in findings:
        lines.append(f"  [{label}] {finding}")
    lines.append("")
    # overall shape
    succ = [r.get("task_success_rate") for r in rows if r["version"] in ORDER]
    if len(succ) == 4 and all(isinstance(x, float) for x in succ):
        shape = " -> ".join(f"{x:.0%}" for x in succ)
        lines.append(f"OVERALL SHAPE: {shape}")
        if succ[-1] - succ[0] >= 0.30:
            lines.append("=> matches 'helps' hypothesis (40%->55%->62%->75%)")
        elif succ[-1] - succ[0] <= 0.05:
            lines.append("=> matches 'no-op' hypothesis (40%->42%->43%->44%) — bottleneck is Planner/Perception")
        else:
            lines.append("=> mixed — read per-layer deltas above")
    return "\n".join(lines)


def analyze_csv(path):
    rows = load_csv(path)
    dts = deltas(rows)
    findings = interpret(rows, dts)
    return render(rows, dts, findings, source=path)


def _selftest():
    """Validate output shape with SYNTHETIC data. Numbers here are fake and
    clearly labeled; this proves the parser/renderer work, nothing more."""
    synth = [
        {"version": "A_raw", "task_success_rate": 0.40, "error_click_rate": 0.30,
         "target_localization_success": 0.55, "verification_false_positive_rate": None,
         "recovery_success_rate": None, "avg_steps": 12.0},
        {"version": "B_grounding", "task_success_rate": 0.55, "error_click_rate": 0.12,
         "target_localization_success": 0.88, "verification_false_positive_rate": None,
         "recovery_success_rate": None, "avg_steps": 11.0},
        {"version": "C_verification", "task_success_rate": 0.62, "error_click_rate": 0.10,
         "target_localization_success": 0.90, "verification_false_positive_rate": 0.10,
         "recovery_success_rate": None, "avg_steps": 10.5},
        {"version": "D_recovery", "task_success_rate": 0.75, "error_click_rate": 0.08,
         "target_localization_success": 0.91, "verification_false_positive_rate": 0.12,
         "recovery_success_rate": 0.70, "avg_steps": 10.0},
    ]
    dts = deltas(synth)
    findings = interpret(synth, dts)
    print("[SELFTEST — synthetic data, NOT real results]")
    print(render(synth, dts, findings, source="<synthetic fixture>"))


def main():
    ap = argparse.ArgumentParser(description="Analyze real_sweep.csv into a verdict")
    ap.add_argument("--csv", default=os.path.join(os.path.dirname(__file__),
                                                  "results", "real_sweep.csv"))
    ap.add_argument("--selftest", action="store_true",
                    help="run with built-in synthetic data to validate output shape")
    ap.add_argument("--markdown", action="store_true",
                    help="also write results/real_sweep_analysis.md")
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return

    text = analyze_csv(args.csv)
    print(text)
    if args.markdown:
        out = os.path.join(os.path.dirname(args.csv), "real_sweep_analysis.md")
        with open(out, "w", encoding="utf-8") as f:
            f.write("# Real-Desktop Sweep Analysis\n\n```\n" + text + "\n```\n")
        print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
