"""A/B runner: reset -> snapshot -> run one arm -> judge -> record.

Two modes that matter before any formal data:

    --selfcheck N   reset N times and compare the initial-state signatures
                    (protocol acceptance: "3 consecutive inits must agree")
    --trial         3 small runs per arm, to validate logging/timeout/reset

Formal runs (``--runs 20``) must not start until the selfcheck passes.

The runner never changes agent behaviour: it only configures the loop
(``runtime_v2``) and records what the run produced. V1's recovery numbers are
derived from its trajectory/log, not by editing V1.
"""

import argparse
import io
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.ab import scenarios as scenario_mod  # noqa: E402
from experiments.ab.events import stats_for  # noqa: E402
from experiments.ab.reset import conversation_texts, reset, _has_menu, title_matches  # noqa: E402

RUNS_DIR = Path(__file__).resolve().parent / "runs"

ARM_FLAGS = {
    # Only the loop differs; every de-modeled layer stays ON in both arms.
    "v1": {"runtime_v2": False},
    "v2": {"runtime_v2": True},
}
COMMON_FLAGS = {"enable_grounding": True, "enable_verification": True,
                "batch_verify": True, "enable_recovery": True}


class _Sink:
    """Collect V2's emitted events (dict form) for normalisation."""

    def __init__(self):
        self.events = []

    def emit(self, ev):
        payload = getattr(ev, "payload", None) or {}
        self.events.append({"type": getattr(ev, "event_type", ""),
                            "payload": payload})


class _LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.buf = io.StringIO()

    def emit(self, record):
        try:
            self.buf.write(record.getMessage() + "\n")
        except Exception:
            pass


def build_agent(arm: str, artifact_dir: str):
    from mio_cua.agent_factory import Agent
    from mio_cua.config import AgentConfig

    flags = dict(COMMON_FLAGS)
    flags.update(ARM_FLAGS[arm])
    cfg = AgentConfig(artifact_dir=artifact_dir, **flags)
    return Agent(cfg)


def _inject_context_menu(pc, perception, scenario):
    """T3: right-click a sidebar entry so a real context menu is open."""
    from mio_cua.models.action import Action
    from experiments.ab.reset import sidebar_candidates, _window_rect, _nodes

    obs = perception.observe()
    rect = _window_rect(obs)
    if not rect:
        return False
    # click the first sidebar row that is not the window title
    rows = [(b[1], b) for _t, txt, b in _nodes(obs)
            if (txt or "").strip() and b[0] < rect[0] + rect[2] * 0.5]
    if not rows:
        return False
    rows.sort()
    _, bbox = rows[0]
    pc.execute(Action("click", "click", {
        "x": bbox[0] + bbox[2] // 2, "y": bbox[1] + bbox[3] // 2,
        "button": "right"}))
    time.sleep(0.4)
    obs = perception.observe()
    return _has_menu(obs)


def _load_trajectory(artifact_dir: Path) -> list:
    """The loop writes trajectory_<id>.json next to its state; read the newest."""
    state = artifact_dir / "state"
    files = sorted(state.glob("trajectory_*.json"),
                   key=lambda p: p.stat().st_mtime) if state.exists() else []
    if not files:
        return []
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except Exception:
        return []


def run_one(arm: str, scenario, args, out_dir: Path) -> dict:
    from mio_cua.automation.input_controller import InputController
    from mio_cua.models.task import Task
    from mio_cua.perception.perception import Perception

    pc = InputController()
    perception = Perception(screenshot_dir=str(out_dir))
    state = reset(perception, pc, app=args.app)
    record = {"arm": arm, "task": scenario.name, "initial": state.as_dict(),
              "reset_ok": state.ok, "problems": state.problems}
    if not state.ok:
        record["discarded"] = "reset failed"
        return record
    # Fail closed on the wrong conversation: sending without confirming the open
    # chat is exactly how a test message reaches a real contact.
    if not title_matches(state.conversation_title, args.target):
        record["discarded"] = (
            f"target conversation not open: header={state.conversation_title!r} "
            f"expected={args.target!r}")
        return record

    had_menu = False
    if scenario.prepare == "context_menu":
        had_menu = _inject_context_menu(pc, perception, scenario)
        record["menu_injected"] = had_menu

    before = conversation_texts(perception.observe())
    record["before_messages"] = before

    sink = _Sink()
    logcap = _LogCapture()
    logging.getLogger("mio_cua").addHandler(logcap)

    agent = build_agent(arm, str(out_dir / "artifacts"))
    task = Task(instruction=scenario.instruction,
                target_context={"app": args.app, "keyword": scenario.keyword},
                metadata={"keyword": scenario.keyword})
    t0 = time.time()
    try:
        result = agent.run(task, event_sinks=[sink] if arm == "v2" else None)
        status, summary = result.status, result.summary
    except Exception as exc:                      # noqa: BLE001 - record, never crash the sweep
        status, summary = "ERROR", f"{type(exc).__name__}: {exc}"
    finally:
        logging.getLogger("mio_cua").removeHandler(logcap)

    duration = round(time.time() - t0, 1)
    after_obs = perception.observe()
    after = conversation_texts(after_obs)
    roles = [(getattr(n, "role", "") or "") for n in
             (getattr(getattr(after_obs, "scene", None), "nodes", []) or [])]

    ctx = {"expected": scenario.expected, "keyword": scenario.keyword,
           "after_messages": after, "before_messages": before,
           "roles_after": roles, "had_menu": had_menu,
           "trajectory": _load_trajectory(out_dir / "artifacts"),
           "status": status}
    verdict = scenario.judge(ctx)

    record.update({
        "status": status, "summary": summary, "duration_s": duration,
        "verdict": verdict.as_dict(),
        "after_messages": after[-3:],
        "stats": stats_for({"trajectory": ctx["trajectory"],
                            "events": sink.events if arm == "v2" else None,
                            "log_text": logcap.buf.getvalue(),
                            "keyword": scenario.keyword}).as_dict(),
        "log_tail": logcap.buf.getvalue().splitlines()[-5:],
    })
    return record


def _write(out_dir: Path, record: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{record['arm']}-{record['task']}-{int(time.time() * 1000)}.json"
    (out_dir / name).write_text(json.dumps(record, ensure_ascii=False, indent=2,
                                           default=str), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="V1/V2 A/B runner (harness only)")
    ap.add_argument("--app", default="微信")
    ap.add_argument("--target", default="文件传输助手")
    ap.add_argument("--message", default="ab-test-message")
    ap.add_argument("--selfcheck", type=int, default=0,
                    help="reset N times and compare initial-state signatures")
    ap.add_argument("--open-check", type=int, default=0,
                    help="open the target chat N times (search + identity only, no messages)")
    ap.add_argument("--expect", default="ok", choices=("ok", "refuse"),
                    help="with --open-check: every attempt must succeed, or every attempt must be refused")
    ap.add_argument("--allow-draft-clear", action="store_true",
                    help="permit wiping an existing composer draft (off by default)")
    ap.add_argument("--trial", action="store_true", help="3 runs/arm/task")
    ap.add_argument("--runs", type=int, default=0, help="formal runs per arm/task")
    ap.add_argument("--tasks", default="T1,T2,T3,T4")
    ap.add_argument("--arms", default="v1,v2")
    ap.add_argument("--out", default=str(RUNS_DIR))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    scens = scenario_mod.build(target=args.target, message=args.message)
    tasks = [t.strip() for t in args.tasks.split(",") if t.strip() in scens]
    arms = [a.strip() for a in args.arms.split(",") if a.strip() in ARM_FLAGS]

    if args.dry_run:
        print(f"tasks={tasks} arms={arms} "
              f"runs={args.runs or (3 if args.trial else 0)} out={args.out}")
        return 0

    if args.selfcheck:
        from mio_cua.automation.input_controller import InputController
        from mio_cua.perception.perception import Perception
        pc, perception = InputController(), Perception()
        sigs, oks = [], []
        for i in range(args.selfcheck):
            st = reset(perception, pc, app=args.app,
                       clear_draft=args.allow_draft_clear)
            sigs.append(st.signature())
            oks.append(st.ok)
            print(f"init {i + 1}: ok={st.ok} sig={st.signature()} "
                  f"nodes={st.node_count} chat={st.conversation_title!r} "
                  f"problems={st.problems}")
        consistent = len(set(sigs)) == 1 and all(oks)
        print("consistent:", consistent)
        return 0 if consistent else 1

    if args.open_check:
        from experiments.ab.open_chat import open_chat
        from mio_cua.automation.input_controller import InputController
        from mio_cua.perception.perception import Perception
        pc, perception = InputController(), Perception()
        passes = 0
        for i in range(args.open_check):
            r = open_chat(pc, perception, app=args.app, target=args.target)
            wanted = r.ok if args.expect == "ok" else (not r.ok)
            passes += 1 if wanted else 0
            print(f"open {i + 1}: ok={r.ok} title={r.title!r} why={r.why} "
                  f"rows={(r.evidence or {}).get('rows')} "
                  f"reason={(r.evidence or {}).get('match_reason')} "
                  f"picked={(r.evidence or {}).get('picked')}")
        print(f"open-check: {passes}/{args.open_check} as expected (expect={args.expect})")
        return 0 if passes == args.open_check else 1

    runs = args.runs or (3 if args.trial else 0)
    if not runs:
        print("nothing to do: pass --selfcheck/--trial/--runs or --dry-run")
        return 2

    out_root = Path(args.out)
    ok = 0
    total = 0
    for task_name in tasks:
        sc = scens[task_name]
        for _ in range(runs):
            for arm in arms:                      # interleaved on purpose
                out_dir = out_root / time.strftime("%Y%m%d-%H%M%S") / arm / task_name
                rec = run_one(arm, sc, args, out_dir)
                _write(out_dir, rec)
                total += 1
                ok += 1 if rec.get("verdict", {}).get("ok") else 0
                v = rec.get("verdict") or {}
                print(f"{task_name} {arm}: ok={v.get('ok')} safe={v.get('safe')} "
                      f"status={rec.get('status')} {v.get('detail', '')}")
    print(f"done: {ok}/{total} judged ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
