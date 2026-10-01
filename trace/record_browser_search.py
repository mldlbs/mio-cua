"""Real Trace Recording: Browser Search — 搜索今日新闻

Task: 在浏览器中搜索"今日新闻"

Records:
  - trace.json (full Trace with PlannerRecord)
  - screenshots/obs_XXX.png (raw screenshots at each observation)
  - failure_report.json (FailureClassifier attribution + quality reports)
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mio_cua.agent_factory import Agent
from mio_cua.config import AgentConfig
from mio_cua.evaluation.trace import TraceRecorder, FailureClassifier
from mio_cua.evaluation.recorder import TraceStore
from mio_cua.models.task import Task
from mio_cua.perception.quality import assess_quality
from mio_cua.scene.graph import SceneGraph, SceneNode

# ── Config ──
#
# Endpoint/model must match what zen-proxy actually serves. The previous
# values (base_url=.../v1 + model=mimo-v2.5-free) were both documented-bad in
# config.zen.yaml: "/v1" 404s on zen-proxy and mimo-v2.5-free returns 404, so
# every run ended at the planner with an HTTP error and only the deterministic
# focus retries ever executed.
BASE_URL = "https://ai.crlkcloud.cyou/v1"
# This endpoint serves a literal model id "default" (GET /v1/models). The
# gpt-5.x names from the opencode config are rejected here:
#   404 model_not_found "not supported by any configured account in this group"
# and omitting the model is 400 "model is required".
MODEL = "default"
API_KEY_ENV = "CK_API_KEY"
# Cloudflare 1010 = "banned based on your browser's signature": a
# Python-urllib / python-requests UA gets 403, a browser UA gets 200.
# providers/openai_compat.py already sends one; every probe here must too.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

TRACE_DIR = Path(__file__).resolve().parent
SCREENSHOTS_DIR = TRACE_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)


def _load_api_key() -> None:
    """Resolve CK_API_KEY from the environment, else a gitignored local file.

    The key must not be hardcoded in this script.
    """
    if os.environ.get(API_KEY_ENV):
        return
    for cand in (TRACE_DIR.parent / ".llm_env", TRACE_DIR / ".llm_env"):
        if not cand.exists():
            continue
        for line in cand.read_text(encoding="utf8").splitlines():
            if line.strip().startswith(API_KEY_ENV + "="):
                os.environ[API_KEY_ENV] = line.split("=", 1)[1].strip()
                return


_load_api_key()

config = AgentConfig(
    base_url=BASE_URL,
    api_key_env=API_KEY_ENV,
    model=MODEL,
    max_steps=20,
    # Was 600s, which only bought ~3 steps while observe() still cost 122s
    # each. After the UIA fix observe is ~5s, so the budget is now bounded by
    # the LLM (60-90s/plan): 20 steps needs well over 20 minutes.
    task_timeout_s=1800,
    artifact_dir=str(TRACE_DIR / "artifacts_v2"),
    # Stay on AgentLoop (V1): its context check is the code under test here.
    # config.zen.yaml sets runtime_v2=true, which would silently swap it out.
    runtime_v2=False,
)


def _preflight():
    """Fail fast when the LLM endpoint is down or the key is missing.

    The first observe burns ~2min on OCR cold start; discovering a dead
    endpoint only when the planner is finally reached wastes that entirely
    (and looks like a loop bug rather than an environment problem).
    """
    import urllib.error
    import urllib.request

    key = os.environ.get(API_KEY_ENV, "")
    if not key:
        raise SystemExit(
            f"[preflight] {API_KEY_ENV} is not set.\n"
            f"  Export it, or put `{API_KEY_ENV}=<key>` in "
            f"{TRACE_DIR.parent / '.llm_env'} (gitignored)."
        )

    url = BASE_URL.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}",
                 "User-Agent": UA},
        method="POST",
    )
    try:
        # Disable the WinINET proxy: on this machine it has pointed at a dead
        # port before and silently breaks TLS.
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=10)
    except urllib.error.HTTPError as e:
        if e.code == 403:  # Cloudflare 1010 ban, not a healthy 4xx
            raise SystemExit(
                f"[preflight] HTTP 403 from {BASE_URL}: Cloudflare UA ban "
                f"(error 1010)?\n  {e.read()[:300]!r}"
            )
        return  # other 4xx/5xx = origin answered, endpoint is up
    except Exception as e:
        raise SystemExit(
            f"[preflight] LLM endpoint unreachable: {BASE_URL}\n"
            f"  {e}\n"
            f"  Check connectivity before running this scenario."
        )


def _reset_state(query: str) -> int:
    """Close residual search-result tabs left behind by a previous run.

    A regression scenario must start from a clean state. Without this, the
    previous run's Bing results tab survives, and the agent correctly observes
    it and declares success on a search it never performed -- trace
    1790784397 ran focus_window -> ctrl+t -> focus_window -> success with ZERO
    `type` actions, yet reported SUCCESS because run 1790783266 had already
    typed the query.

    Detection uses window titles only (win32), so it costs ~ms and never
    touches OCR. Set MIO_SKIP_RESET=1 to bypass.
    """
    import time as _t

    if os.environ.get("MIO_SKIP_RESET"):
        return 0

    from mio_cua.automation.input_controller import InputController
    from mio_cua.automation.windows import (
        _windows_matching_title,
        focus_window,
        get_active_process,
    )
    from mio_cua.models.action import Action

    controller = InputController()
    closed = 0
    for _ in range(8):
        if not _windows_matching_title(query):
            break
        if not focus_window(query):
            break
        _t.sleep(0.4)
        # Never ctrl+w something that is not a browser: another app could in
        # principle carry the query in its title.
        if get_active_process() not in ("msedge", "chrome", "firefox", "iexplore"):
            break
        result = controller.execute(
            Action(id="scenario-reset", type="key", params={"keys": "ctrl+w"})
        )
        if not result.sent:
            break
        closed += 1
        _t.sleep(0.6)
    return closed


def _performed_this_run(trace, query: str) -> bool:
    """True when this run itself typed the search query.

    The terminal screenshot alone cannot tell an earned success from an
    inherited one; only the recorded action chain can.
    """
    for entry in trace.entries:
        action = entry.action
        if action and action.type == "type":
            text = str((action.params or {}).get("text", ""))
            if query in text:
                return True
    return False


# ── Task ──

task = Task(
    instruction="打开浏览器，在搜索引擎中搜索「今日新闻」",
    target_context={"app": "Edge"},
)

# ── Record ──

print("=" * 60)
print("Scenario: Browser Search")
print(f"Task: {task.instruction}")
print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

agent = Agent(config)
recorder = TraceRecorder(agent)

print("\n[0/4] Preflight: LLM endpoint...")
_preflight()
print(f"  OK: {BASE_URL} model={MODEL} key_env={API_KEY_ENV}")
if os.environ.get("MIO_PREFLIGHT_ONLY"):
    raise SystemExit(0)  # config/probe check without seizing the desktop

print("\n[1/4] Resetting state, then running agent...")
_reset_closed = _reset_state("今日新闻")
if _reset_closed:
    print(f"  Reset: closed {_reset_closed} residual tab(s) left by a previous run")
else:
    print("  Reset: clean start (no residual tab)")
start = time.time()
trace = recorder.run(task)
duration = time.time() - start
performed = _performed_this_run(trace, "今日新闻")
print(f"  Done in {duration:.1f}s, {len(trace.entries)} steps")
print(f"  Typed the query this run: {'YES' if performed else 'NO (state inherited)'}")

# ── Save trace ──

print("\n[2/4] Saving trace.json...")
store = TraceStore(str(TRACE_DIR))
store.save(trace)
print(f"  Saved: {TRACE_DIR / 'trace.json'}")

# ── Save screenshots ──

print("\n[3/4] Saving screenshots...")
for i, entry in enumerate(trace.entries):
    obs = entry.obs_before
    if obs and hasattr(obs, "screenshot_path") and obs.screenshot_path and os.path.exists(obs.screenshot_path):
        dst = SCREENSHOTS_DIR / f"obs_{i:03d}.png"
        import shutil
        shutil.copy2(obs.screenshot_path, str(dst))
        print(f"  Step {i}: {dst.name}")
    else:
        print(f"  Step {i}: no screenshot")

# ── Failure classification ──

print("\n[4/4] Classifying failures...")
fc = FailureClassifier()
results = fc.classify_trace(trace, goal_keyword="今日新闻", goal_app="Edge")
summary = fc.summary(results)

# ── Build failure report ──

failure_report = {
    "scenario": "browser_search",
    "task": task.instruction,
    "trace_id": trace.trace_id,
    "timestamp": trace.created_at,
    "duration_s": round(duration, 2),
    "total_steps": len(trace.entries),
    # Guards against a false SUCCESS: an end state that merely *looks* right
    # because a previous run already searched (see _performed_this_run).
    "search_performed_this_run": performed,
    # This scenario only counts as an earned pass if the query was typed here:
    # a clean terminal screenshot can still be inherited state.
    "valid": performed,
    "failure_summary": summary,
    "step_results": results,
    "step_details": [],
}

for i, (entry, result) in enumerate(zip(trace.entries, results)):
    obs = entry.obs_before
    scene = SceneGraph(active_window=getattr(obs, "active_window", "") if obs else "")
    if obs:
        for nd in getattr(obs, "scene_nodes", []):
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
        "active_window": getattr(obs, "active_window", "") if obs else "",
        "action_type": entry.action.type if entry.action else None,
        "action_params": entry.action.params if entry.action else None,
        "classification": result["category"],
        "detail": result["detail"],
        "confidence": result["confidence"],
        "scene_nodes": len(getattr(obs, "scene_nodes", [])) if obs else 0,
    }
    if quality:
        detail["quality"] = {
            "node_count": quality.node_count,
            "confidence": round(quality.confidence, 3),
            "is_usable": quality.is_usable,
            "has_search_box": quality.has_search_box,
        }
    if entry.planner:
        detail["planner"] = {
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
print(f"  Typed query:    {'yes' if performed else 'NO (inherited state)'}")
if not performed:
    print("  !! This run never typed the query — SUCCESS reflects inherited state.")
print()

for i, r in enumerate(results):
    detail = failure_report["step_details"][i]
    nodes = detail.get("scene_nodes", 0)
    act = detail.get("action_type", "?")
    if r["category"]:
        print(f"  Step {i}: [{r['category']:16s}] nodes={nodes:3d} act={act}")
    else:
        print(f"  Step {i}: [OK               ] nodes={nodes:3d} act={act}")

print()
print(f"Trace:    {TRACE_DIR / 'trace.json'}")
print(f"Report:   {report_path}")
print(f"Photos:   {SCREENSHOTS_DIR}")