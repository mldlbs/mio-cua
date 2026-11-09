"""A/B runner: reset -> snapshot -> run one arm -> judge -> record.

Two modes that matter before any formal data:

    --selfcheck N   reset N times and compare the initial-state signatures
    --open-check N  prove the target chat can be opened (search + identity)
    --trial         3 small runs per arm/task, to validate logging/timeout/reset

Formal runs (``--runs 20``) must not start until those pass.

The runner never changes agent behaviour: it only configures the loop
(``runtime_v2``) and records what the run produced. V1's recovery numbers are
derived from its trajectory/log, not by editing V1.
"""

import argparse
import io
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.ab import scenarios as scenario_mod  # noqa: E402
from experiments.ab.events import stats_for  # noqa: E402
from experiments.ab.reset import (  # noqa: E402
    _composer_bbox,
    _has_menu,
    conversation_texts,
    reset,
    title_matches,
)

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


def _load_llm_env() -> None:
    """Load the project's LLM credentials (desktop-agent/.llm_env).

    Without this, AgentConfig falls back to api.openai.com and every run dies on
    a connection timeout instead of exercising the agent.
    """
    key_env = "CK_API_KEY"
    if os.environ.get(key_env):
        return
    for cand in (Path(__file__).resolve().parents[2] / ".llm_env",):
        if not cand.exists():
            continue
        for line in cand.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith(key_env + "="):
                os.environ[key_env] = line.split("=", 1)[1].strip()
                return


def build_agent(arm: str, artifact_dir: str):
    from mio_cua.agent_factory import Agent
    from mio_cua.config import AgentConfig

    _load_llm_env()
    flags = dict(COMMON_FLAGS)
    flags.update(ARM_FLAGS[arm])
    cfg = AgentConfig(
        base_url="https://ai.crlkcloud.cyou/v1",
        model="default",
        api_key_env="CK_API_KEY",
        artifact_dir=artifact_dir,
        **flags,
    )
    return Agent(cfg)


def _git_sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"],
                             cwd=str(Path(__file__).resolve().parents[2]),
                             capture_output=True, text=True, timeout=10)
        return (out.stdout or "").strip()
    except Exception:
        return ""


def _read_clipboard() -> str:
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT) or ""
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return ""
    return ""


def _inject_composer_menu(pc, perception) -> bool:
    """T3: right-click the COMPOSER so the menu is an edit menu (cut/copy/paste).

    Right-clicking a chat row would offer destructive chat actions (delete,
    pin, ...), which a confused agent could execute on real data. The composer's
    edit menu cannot alter chat content.
    """
    from mio_cua.models.action import Action

    obs = perception.observe()
    box = _composer_bbox(obs)
    if not box:
        return False
    pc.execute(Action("click", "click", {
        "x": box[0] + box[2] // 2, "y": box[1] + box[3] // 2,
        "button": "right"}))
    time.sleep(0.4)
    return _has_menu(perception.observe())


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


def _draft(perception) -> str:
    """Visible text inside the composer band (a human draft would show here)."""
    from experiments.ab.reset import _composer_text
    return _composer_text(perception.observe())


def run_one(arm: str, scenario, args, out_dir: Path) -> dict:
    from mio_cua.automation.input_controller import InputController
    from mio_cua.models.task import Task
    from mio_cua.perception.perception import Perception

    pc = InputController()
    perception = Perception(screenshot_dir=str(out_dir))
    state = reset(perception, pc, app=args.app)
    record = {"arm": arm, "task": scenario.name, "git_sha": _git_sha(),
              "initial": state.as_dict(), "reset_ok": state.ok,
              "problems": state.problems}
    if not state.ok:
        record["discarded"] = "reset failed"
        return record
    # Fail closed on the wrong conversation: sending without confirming the open
    # chat is exactly how a test message reaches a real contact. The gate opens
    # it via search (unique exact match) and re-verifies the header; in manual
    # mode the chat must already be open and is only verified.
    from experiments.ab.open_chat import open_chat
    if getattr(args, "open_mode", "auto") == "manual":
        obs0 = perception.observe()
        from experiments.ab.reset import conversation_title
        title0 = conversation_title(obs0)
        opened_ok = title_matches(title0, args.target)
        record["open"] = {"mode": "manual", "title": title0, "ok": opened_ok}
        if not opened_ok:
            record["discarded"] = (
                f"target conversation not open (manual mode): header={title0!r} "
                f"expected={args.target!r}")
            return record
    else:
        opened = open_chat(pc, perception, app=args.app, target=args.target)
        record["open"] = opened.as_dict()
        if not opened.ok:
            record["discarded"] = f"target conversation not confirmed: {opened.why}"
            return record
    if not title_matches(opened.title, args.target):
        record["discarded"] = (
            f"target conversation not open: header={opened.title!r} "
            f"expected={args.target!r}")
        return record

    had_menu = False
    if scenario.prepare == "composer_menu":
        had_menu = _inject_composer_menu(pc, perception)
        record["menu_injected"] = had_menu
        if not had_menu:
            record["discarded"] = "T3 injection failed: no menu appeared"
            return record

    before_obs = perception.observe()
    before = conversation_texts(before_obs)
    before_draft = _draft(perception)
    before_clip = _read_clipboard()
    record.update({"before_messages": before[-3:], "before_draft": before_draft,
                   "before_clip_len": len(before_clip)})

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
    after_draft = _draft(perception)
    after_clip = _read_clipboard()

    ctx = {"expected": scenario.expected, "keyword": scenario.keyword,
           "after_messages": after, "before_messages": before,
           "roles_after": roles, "had_menu": had_menu,
           "before_draft": before_draft, "after_draft": after_draft,
           "before_clip": before_clip, "after_clip": after_clip,
           "trajectory": _load_trajectory(out_dir / "artifacts"),
           "status": status}
    verdict = scenario.judge(ctx)

    record.update({
        "status": status, "summary": summary, "duration_s": duration,
        "verdict": verdict.as_dict(),
        "after_messages": after[-3:],
        "after_draft": after_draft, "after_clip_len": len(after_clip),
        "stats": stats_for({"trajectory": ctx["trajectory"],
                            "events": sink.events if arm == "v2" else None,
                            "log_text": logcap.buf.getvalue(),
                            "keyword": scenario.keyword}).as_dict(),
        "events": sink.events if arm == "v2" else None,
        "log_tail": logcap.buf.getvalue().splitlines()[-5:],
    })
    return record


def run_one_notepad(arm: str, scenario, args, out_dir: Path) -> dict:
    """Notepad variant of run_one: disposable process, exact state."""
    from mio_cua.automation.input_controller import InputController
    from mio_cua.models.task import Task
    from experiments.ab import notepad as npad

    pc = InputController()
    hwnd = npad.reset(npad.TEST_DIR)
    record = {"arm": arm, "task": scenario.name, "git_sha": _git_sha(),
              "site": "notepad", "test_dir": str(npad.TEST_DIR)}
    if hwnd is None:
        record["discarded"] = "notepad reset failed (no empty document)"
        return record
    before = npad.snapshot(hwnd)
    record["before"] = before

    if scenario.prepare == "find_dialog":
        injected = npad.inject_find_dialog(pc, hwnd)
        record["menu_injected"] = injected
        if not injected:
            record["discarded"] = "T3 injection failed: no 查找 dialog"
            npad.kill_all()
            return record

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
    except Exception as exc:                      # noqa: BLE001
        status, summary = "ERROR", f"{type(exc).__name__}: {exc}"
    finally:
        logging.getLogger("mio_cua").removeHandler(logcap)
        duration = round(time.time() - t0, 1)
        after_hwnd = npad.main_window() or hwnd
        after = npad.snapshot(after_hwnd)

    ctx = {"expected": scenario.expected, "keyword": scenario.keyword,
           "doc_after": after.get("doc"), "dialogs_after": after.get("dialogs"),
           "files_before": before.get("files"), "files_after": after.get("files"),
           "out_path": str(npad.TEST_DIR / npad.OUT_FILE),
           "before_messages": [], "after_messages": [],
           "trajectory": _load_trajectory(out_dir / "artifacts"),
           "status": status}
    verdict = scenario.judge(ctx)
    record.update({"status": status, "summary": summary, "duration_s": duration,
                   "after": after, "verdict": verdict.as_dict(),
                   "stats": stats_for({"trajectory": ctx["trajectory"],
                                       "events": sink.events if arm == "v2" else None,
                                       "log_text": logcap.buf.getvalue(),
                                       "keyword": scenario.keyword}).as_dict(),
                   "events": sink.events if arm == "v2" else None,
                   "log_tail": logcap.buf.getvalue().splitlines()[-5:]})
    npad.kill_all()
    return record


def _write(out_dir: Path, record: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{record['arm']}-{record['task']}-{int(time.time() * 1000)}.json"
    (out_dir / name).write_text(json.dumps(record, ensure_ascii=False, indent=2,
                                           default=str), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="V1/V2 A/B runner (harness only)")
    ap.add_argument("--app", default="记事本")
    ap.add_argument("--site", default="notepad", choices=("notepad", "wechat"),
                    help="which app the trial drives (notepad is the migrated target)")
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
    ap.add_argument("--open-mode", default="auto", choices=("auto", "manual"),
                    help="auto: search+unique-match+verify; manual: the chat must already be open (verified only)")
    args = ap.parse_args(argv)

    if args.site == "notepad":
        from experiments.ab import notepad as npad
        scens = scenario_mod.build_notepad(str(npad.TEST_DIR), message=args.message)
    else:
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
    consecutive_aborts = 0
    session = time.strftime("%Y%m%d-%H%M%S")
    for task_name in tasks:
        sc = scens[task_name]
        for _ in range(runs):
            for arm in arms:                      # interleaved on purpose
                out_dir = out_root / session / arm / task_name
                rec = (run_one_notepad(arm, sc, args, out_dir)
                       if args.site == "notepad" else run_one(arm, sc, args, out_dir))
                _write(out_dir, rec)
                total += 1
                v = rec.get("verdict") or {}
                ok += 1 if v.get("ok") else 0
                if rec.get("discarded"):
                    consecutive_aborts += 1
                    print(f"{task_name} {arm}: DISCARDED {rec['discarded']}")
                    if consecutive_aborts >= 2:
                        print("aborting the trial: two consecutive hard-gate failures "
                              "-- fix the harness before collecting more data")
                        print(f"done: {ok}/{total} judged ok")
                        return 3
                else:
                    consecutive_aborts = 0
                    print(f"{task_name} {arm}: ok={v.get('ok')} safe={v.get('safe')} "
                          f"status={rec.get('status')} {v.get('detail', '')}")
    print(f"done: {ok}/{total} judged ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
