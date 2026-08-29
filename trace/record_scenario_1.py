"""Real Trace Recording: Scenario 1 — 目标发现

Task: 找到名为"兴蓉"的群并打开

Records:
  - trace.json (full Trace with PlannerRecord)
  - screenshots/obs_XXX.png (raw screenshots at each observation)
  - failure_report.json (FailureClassifier attribution + quality reports)

Perception config (fixed for reproducibility):
  - UIA: enabled
  - OCR: rapidocr_onnxruntime (CPU)
  - Fallback: enabled (enhanced OCR + region analysis)
  - QualityGate: enabled (confidence-based scoring)
"""

import json
import os
import sys
import time
from pathlib import Path
from dataclasses import asdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mio_cua.agent_factory import Agent
from mio_cua.config import AgentConfig
from mio_cua.evaluation.trace import TraceRecorder, FailureClassifier
from mio_cua.evaluation.recorder import TraceStore
from mio_cua.models.task import Task
from mio_cua.perception.quality import assess_quality, QualityReport
from mio_cua.scene.graph import SceneGraph, SceneNode

# ── Config ──

TRACE_DIR = Path(__file__).resolve().parent
SCREENSHOTS_DIR = TRACE_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

config = AgentConfig(
    base_url="http://127.0.0.1:8000/v1",
    api_key_env="ZEN_API_KEY",
    model="mimo-v2.5-free",
    max_steps=20,
    task_timeout_s=240,
    artifact_dir=str(TRACE_DIR / "artifacts_v2"),
)

os.environ["ZEN_API_KEY"] = "sk-xzv73DsVZtWggFbm06xk4XH3lbLNO7RlbE2Fd0UXawhSopFyif1nixnNPfPzxkkJ"

# ── Task ──

task = Task(
    instruction="找到名为「兴蓉」的群并打开",
    target_context={"app": "WeChat"},
)

# ── Record ──

print("=" * 60)
print("Scenario 1 v2: 目标发现 (with OCR)")
print(f"Task: {task.instruction}")
print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

agent = Agent(config)
recorder = TraceRecorder(agent)

print("\n[1/4] Running agent with trace recording...")
start = time.time()
trace = recorder.run(task)
duration = time.time() - start
print(f"  Done in {duration:.1f}s, {len(trace.entries)} steps")

# ── Save trace ──

print("\n[2/4] Saving trace.json...")
store = TraceStore(str(TRACE_DIR))
store.save(trace)
print(f"  Saved: {TRACE_DIR / 'trace.json'}")

# ── Save screenshots ──

print("\n[3/4] Saving screenshots...")
for i, entry in enumerate(trace.entries):
    obs = entry.obs_before
    if obs.screenshot_path and os.path.exists(obs.screenshot_path):
        dst = SCREENSHOTS_DIR / f"obs_{i:03d}.png"
        import shutil
        shutil.copy2(obs.screenshot_path, str(dst))
        print(f"  Step {i}: {dst.name}")
    else:
        print(f"  Step {i}: no screenshot (path={obs.screenshot_path})")

# ── Failure classification + quality reports ──

print("\n[4/4] Classifying failures...")
fc = FailureClassifier()
results = fc.classify_trace(trace, goal_keyword="兴蓉", goal_app="WeChat")
summary = fc.summary(results)

# ── Build failure report with quality reports ──

failure_report = {
    "scenario": "target_discovery",
    "task": task.instruction,
    "trace_id": trace.trace_id,
    "timestamp": trace.created_at,
    "duration_s": round(duration, 2),
    "total_steps": len(trace.entries),
    "perception_config": {
        "uia": True,
        "ocr": "rapidocr_onnxruntime",
        "fallback": True,
        "quality_gate": True,
        "quality_scoring": "confidence_based",
    },
    "failure_summary": summary,
    "step_results": results,
    "step_details": [],
}

for i, (entry, result) in enumerate(zip(trace.entries, results)):
    obs = entry.obs_before
    # Build SceneGraph from trace scene_nodes for quality assessment
    scene = SceneGraph(active_window=obs.active_window)
    for nd in obs.scene_nodes:
        scene.nodes.append(SceneNode(
            id=nd.get("id", 0),
            type=nd.get("type", "unknown"),
            bbox=tuple(nd.get("bbox", [0, 0, 0, 0])),
            text=nd.get("text", ""),
            semantic=nd.get("semantic", ""),
        ))
    quality = assess_quality(scene) if scene.nodes else None

    detail = {
        "step": i,
        "active_window": obs.active_window,
        "action_type": entry.action.type if entry.action else None,
        "action_params": entry.action.params if entry.action else None,
        "classification": result["category"],
        "detail": result["detail"],
        "confidence": result["confidence"],
        "obs_screenshot": f"screenshots/obs_{i:03d}.png",
        "scene_nodes": len(obs.scene_nodes),
    }
    if quality:
        detail["quality"] = {
            "node_count": quality.node_count,
            "interactive_count": quality.interactive_count,
            "coverage_score": round(quality.coverage_score, 3),
            "interaction_score": round(quality.interaction_score, 3),
            "semantic_score": round(quality.semantic_score, 3),
            "confidence": round(quality.confidence, 3),
            "is_usable": quality.is_usable,
            "reason": quality.reason,
            "has_search_box": quality.has_search_box,
        }
    if entry.planner:
        detail["planner"] = {
            "prompt_preview": entry.planner.prompt[:300],
            "llm_response_preview": entry.planner.llm_response[:300],
            "decision_state": entry.planner.decision_state,
        }
    failure_report["step_details"].append(detail)

report_path = TRACE_DIR / "failure_report.json"
with open(report_path, "w", encoding="utf-8") as f:
    json.dump(failure_report, f, ensure_ascii=False, indent=2)
print(f"  Saved: {report_path}")

# ── Print summary ──

print("\n" + "=" * 60)
print("RESULTS")
print("=" * 60)
print(f"  Total steps:    {summary['total_steps']}")
print(f"  Perception:     {summary['perception_rate']:.0%}")
print(f"  Planner:        {summary['planner_rate']:.0%}")
print(f"  Action:         {summary['action_rate']:.0%}")
print(f"  Environment:    {summary['environment_rate']:.0%}")
print()

for i, r in enumerate(results):
    detail = failure_report["step_details"][i]
    q = detail.get("quality", {})
    nodes = detail.get("scene_nodes", 0)
    usable = q.get("is_usable", "?")
    conf = q.get("confidence", "?")
    act = detail.get("action_type", "?")
    if r["category"]:
        print(f"  Step {i}: [{r['category']:16s}] nodes={nodes:3d} usable={usable} conf={conf} act={act}")
    else:
        print(f"  Step {i}: [OK               ] nodes={nodes:3d} usable={usable} conf={conf} act={act}")

print()
print(f"Trace:    {TRACE_DIR / 'trace.json'}")
print(f"Report:   {report_path}")
print(f"Photos:   {SCREENSHOTS_DIR}")
