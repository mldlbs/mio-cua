"""Real Trace Recording: ChatGPT web chat — 让它用不超过50个字回复

Task: 打开 Chrome 进 chatgpt.com，发送提示词，等回复完整

Unlike the browser-search scenario the PASS/FAIL here is decided by the
script, never by the agent's own `success` claim: ChatGPT replies are
streamed, so an agent that stops early still sees *some* text and would
happily report success on a truncated answer.

  valid = len(reply without whitespace) <= 50

Recon notes (trace/recon_chatgpt.py, run against the signed-in profile):
  * OmniParser is unavailable here ("web controls disabled"), so there is no
    input/button role to target -- everything is OCR text + bbox.
  * The blue send control carries no text at all (OCR read the mic glyph as
    "9"), so sending is done with Enter, not by clicking.
  * The composer placeholder "有问题，随便问" anchors the floor of the
    transcript: anything with y above it and x inside the centre panel is
    conversation content; x < panel_left is the sidebar.
"""

import json
import os
import re
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

# Endpoint/model: see record_browser_search.py for why these exact values.
BASE_URL = "https://ai.crlkcloud.cyou/v1"
MODEL = "default"
API_KEY_ENV = "CK_API_KEY"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

PROMPT = "请严格用不超过50个字介绍你自己"
MAX_REPLY_CHARS = 50

# How far left/right of the composer the transcript may extend. ChatGPT's
# sidebar ends around x=190 while the composer starts past x=1000, so 400px
# comfortably clears the sidebar without reaching the WorkBuddy popup at
# x>2180.
_COMPOSER_ANCHOR = 400

# Below our own message the transcript column also holds the message/reply
# control labels, the ad block and the footer disclaimer. Measured on the
# 2026-10-01 run: taking all of them made the reply 222 chars when the real
# answer was 36 -- so they must never count toward MAX_REPLY_CHARS.
# Labels are matched by prefix (they vary with locale and feature flags), the
# ad and the disclaimer by their distinctive wording.
_UI_NOISE_RE = re.compile(
    r"也可能会犯错"                                        # footer disclaimer
    r"|^\s*广告\s*$"                                       # ad marker
    r"|CARTESIA|Real-Time Voice|One APl|production voice|unique voice|Find your"
    r"|^(复制|评价|编辑|分享|切换|更多|点赞|点踩|打开|关闭|重试"
    r"|重新生成|重新|朗读|继续生成|继续|发送|停止|引\w{0,4}用)",   # control labels
    re.I,
)

TRACE_DIR = Path(__file__).resolve().parent
SCREENSHOTS_DIR = TRACE_DIR / "screenshots_chatgpt"
SCREENSHOTS_DIR.mkdir(exist_ok=True)


def _load_api_key() -> None:
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
    # Streaming replies need waiting rounds on top of the send round.
    task_timeout_s=1800,
    artifact_dir=str(TRACE_DIR / "artifacts_chatgpt"),
    runtime_v2=False,
)


def _preflight():
    """Fail fast when the LLM endpoint is down (see browser-search notes).

    This only answers "is the endpoint there": the POST carries an empty body
    on purpose, so a 400/422 from the server is proof of life, not a failure.
    A TLS timeout is -- and the endpoint flaps on those, so retry first.
    """
    import urllib.error
    import urllib.request

    key = os.environ.get(API_KEY_ENV, "")
    if not key:
        raise SystemExit(f"[preflight] {API_KEY_ENV} is not set.")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    last = None
    for attempt in range(1, 4):
        req = urllib.request.Request(
            BASE_URL.rstrip("/") + "/chat/completions",
            data=b"{}",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}",
                     "User-Agent": UA},
            method="POST",
        )
        try:
            opener.open(req, timeout=20)
            return
        except urllib.error.HTTPError as e:
            if e.code in (400, 422, 429):
                return
            if e.code == 401:
                raise SystemExit(f"[preflight] HTTP 401 -- {API_KEY_ENV} rejected")
            if e.code == 403:
                raise SystemExit(f"[preflight] HTTP 403 (Cloudflare UA ban): "
                                 f"{e.read()[:300]!r}")
            if e.code == 404:
                raise SystemExit(f"[preflight] HTTP 404 -- wrong base_url: {BASE_URL}")
            last = e
        except Exception as e:
            last = e
        print(f"  attempt {attempt}/3 failed: {last} -- retrying")
        time.sleep(2)
    raise SystemExit(f"[preflight] LLM endpoint unreachable: {BASE_URL}\n  {last}")


def _preflight_chatgpt_site() -> None:
    """Reachability only -- DNS for chatgpt.com is poisoned on this box, so the
    request must go through the local WinINET proxy that Edge/Chrome use.
    """
    import urllib.error
    import urllib.request

    proxy = os.environ.get("MIO_HTTP_PROXY") or _wininet_proxy()
    handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {})]
    opener = urllib.request.build_opener(*handlers)
    last = None
    for attempt in range(1, 4):
        req = urllib.request.Request(
            "https://chatgpt.com/",
            headers={"User-Agent": UA,
                     "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                     "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
                     "Sec-Fetch-Site": "none", "Upgrade-Insecure-Requests": "1"},
        )
        try:
            opener.open(req, timeout=25)
            return
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise SystemExit(f"[preflight] chatgpt.com returned {e.code} -- "
                                 f"sign-in wall or proxy egress blocked?")
            last = e
        except Exception as e:
            last = e
        print(f"  attempt {attempt}/3 failed: {last} -- retrying")
        time.sleep(3)
    raise SystemExit(f"[preflight] chatgpt.com unreachable via {proxy or 'direct'}\n  {last}")


def _wininet_proxy() -> str:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
            enabled, _ = winreg.QueryValueEx(k, "ProxyEnable")
            server, _ = winreg.QueryValueEx(k, "ProxyServer")
            if enabled and server:
                return server if "://" in server else f"http://{server}"
    except OSError:
        pass
    return ""


def _ensure_foreground() -> None:
    """Put a ChatGPT tab in front so the acceptance read is of the right page.

    The agent's last action is whatever it did last; nothing guarantees Chrome
    still owns the foreground when we start measuring.
    """
    from mio_cua.automation.windows import focus_window, get_active_window
    try:
        current = get_active_window()
    except Exception:
        current = ""
    if "chatgpt" in current.lower():
        return
    if not focus_window("ChatGPT"):
        focus_window("Chrome")


# ── Task ──

task = Task(
    instruction=(
        f"打开谷歌浏览器，进入 chatgpt.com 的对话页面。\n"
        f"把下面这句话发送给对方，并等待对方回复完整：\n"
        f"「{PROMPT}」\n"
        f"注意：对方回复是逐字出现的，必须等它写完再结束。"
    ),
    target_context={"app": "Chrome"},
)


# ── Transcript extraction (the objective acceptance check) ──

def _node_tuples(obs):
    """Normalize a node list to (type, text, bbox).

    Accepts both shapes in play here:
      * a live ``Observation`` whose ``scene.nodes`` are SceneNode dataclasses
      * a recorded ``ObsFrame`` whose ``scene_nodes`` are plain dicts
    """
    scene = getattr(obs, "scene", None)
    if scene is not None and getattr(scene, "nodes", None):
        return [(getattr(n, "type", ""), getattr(n, "text", "") or "",
                 getattr(n, "bbox", None)) for n in scene.nodes]
    out = []
    for nd in (getattr(obs, "scene_nodes", None) or []):
        if isinstance(nd, dict):
            out.append((nd.get("type", ""), nd.get("text", "") or "", nd.get("bbox")))
        else:
            out.append((getattr(nd, "type", ""), getattr(nd, "text", "") or "",
                        getattr(nd, "bbox", None)))
    return out


def _layout(nodes):
    """Return (left, right, floor) of the transcript column, or (None, None, None).

    Horizontal bounds come from the input control: it is the one element that
    must sit inside the conversation column, ChatGPT's sidebar ends far to its
    left, and the WorkBuddy overlay sits beyond its right edge.

    ``floor`` is the top of the whole composer ROW, not of the input itself.
    The `+`, 思考 and microphone buttons sit ~8px *above* the input (measured
    y=849 vs y=853 in recon_chatgpt_ui.json) and would otherwise be read back
    as part of the answer.

    Anchoring on the largest group node does not work: Chrome's UIA tree hands
    back a full-screen group (0, 0, 2560, 1560) that swallows the sidebar.
    """
    field = None       # the input control -- defines the column
    row_top = None     # top edge of the composer row
    fallback = None    # OCR-only captures where nothing is typed 'input'
    for ntype, text, bbox in nodes:
        if not bbox or len(bbox) < 4:
            continue
        if "随便问" not in text and "有问题" not in text:
            continue
        if fallback is None:
            fallback = bbox
        if ntype in ("input", "group", "button"):
            if row_top is None or bbox[1] < row_top:
                row_top = bbox[1]
            if ntype == "input" and field is None:
                field = bbox

    col = field or fallback
    if col is None:
        return None, None, None

    x, w = col[0], col[2]
    floor = row_top if row_top is not None else col[1]
    return max(0, x - _COMPOSER_ANCHOR), x + w + _COMPOSER_ANCHOR, floor


def _is_own_message(text):
    """Does this node carry what we sent? Match on distinctive fragments: OCR
    mangles at most one character of a five-char phrase, while a bare prefix
    like '请严格用' would also fire on a reply that quotes us.
    """
    return any(f in text for f in ("介绍你自己", "不超过50", "请严格用"))


def _is_ui_noise(text):
    """Is this node chat chrome rather than the answer?

    The transcript column is not only prose: control labels sit directly under
    our message and under the reply, an ad block renders between them, and the
    disclaimer trails at the bottom. All of them land between ``user_y`` and
    the composer, so filtering here is the only place it can happen.
    """
    return bool(_UI_NOISE_RE.search((text or "").strip()))


def _extract_reply(obs):
    """Return the assistant's reply text as seen in one observation.

    Layout rules, from the recon captures:
      * the transcript column is anchored on the composer (see ``_layout``) --
        the sidebar sits far left of it, the WorkBuddy popup far right
      * y > 200 skips browser chrome; y < floor skips the input row itself
      * the reply is always *below* our own message -- so a page still showing
        only the greeting can never be mistaken for an answer

    Returns the answer prose only: control labels, ad blocks and the
    disclaimer between the prompt and the composer are skipped (see
    ``_is_ui_noise``). Returns ("", reason) when no message of ours is on
    screen at all, or when nothing below it reads as prose.
    """
    nodes = _node_tuples(obs)
    if not nodes:
        return "", "no scene nodes"

    left, right, floor = _layout(nodes)
    if left is None:
        return "", "composer not found"

    user_y = None
    for ntype, text, bbox in nodes:
        if ntype == "group" or not bbox or len(bbox) < 4:
            continue
        x, y = bbox[0], bbox[1]
        if not (left <= x <= right) or y <= 200:
            continue
        if floor is not None and y >= floor:
            continue
        if _is_own_message(text):
            user_y = y if user_y is None else max(user_y, y)
    if user_y is None:
        return "", "prompt not in transcript"

    pieces = []
    for ntype, text, bbox in nodes:
        if ntype == "group":
            continue
        text = text.strip()
        if not text or not bbox or len(bbox) < 4:
            continue
        x, y = bbox[0], bbox[1]
        if not (left <= x <= right):
            continue
        if y <= user_y:
            continue
        if floor is not None and y >= floor:
            continue
        if _is_own_message(text):
            continue
        pieces.append((y, x, text))

    if not pieces:
        return "", "prompt present but no reply yet"

    pieces.sort()

    # Prose only. The nodes under our message are, in order: its control
    # labels, the answer, the answer's control labels, an ad block and the
    # disclaimer (measured: 19 nodes / 222 chars vs an answer of 36). Skip the
    # chrome that precedes the answer and stop at the first piece after it, so
    # a later block can never leak in. No length threshold: an answer may be
    # brief, and by this point every control label has been filtered out.
    collected = []
    for _, _, text in pieces:
        if _is_ui_noise(text):
            if collected:
                break
            continue
        collected.append(text)

    if not collected:
        return "", f"{len(pieces)} node(s) below the prompt but none is prose"

    return (
        " ".join(collected),
        f"{len(collected)} of {len(pieces)} node(s) below the prompt are the reply",
    )


def _settle(perception, timeout_s=90.0, quiet_s=3.0, interval_s=2.0):
    """Poll until the transcript stops changing.

    ChatGPT streams. Reading once right after the agent stops measures a
    *partial* reply, and a partial reply is always <= MAX_REPLY_CHARS, so a
    truncated answer would pass. Wait for two consecutive identical readings.
    """
    best_text, why, best_obs = "", "timeout", None
    stable_since, last = None, None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        obs = perception.observe()
        text, why = _extract_reply(obs)
        if text and text == last:
            if stable_since and time.time() - stable_since >= quiet_s:
                return text, why, obs, True
        else:
            stable_since = time.time() if text else None
        last, best_text, best_obs = text, text, obs
        time.sleep(interval_s)
    return best_text, why, best_obs, False


def _char_count(text: str) -> int:
    """Length that ignores whitespace -- '字数' as a human would count it."""
    return len(re.sub(r"\s+", "", text or ""))


# ── Run ──
def main():

    print("=" * 60)
    print("Scenario: ChatGPT Chat")
    print(f"Task: {task.instruction.splitlines()[0]}")
    print(f"Prompt: {PROMPT}")
    print(f"Acceptance: reply <= {MAX_REPLY_CHARS} chars")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    agent = Agent(config)
    recorder = TraceRecorder(agent)

    print("\n[0/4] Preflight: endpoints...")
    _preflight()
    print(f"  LLM  OK: {BASE_URL} model={MODEL}")
    _preflight_chatgpt_site()
    print("  Site OK: chatgpt.com reachable via proxy")
    if os.environ.get("MIO_PREFLIGHT_ONLY"):
        raise SystemExit(0)

    print("\n[1/4] Running agent with trace recording...")
    start = time.time()
    trace = recorder.run(task)
    duration = time.time() - start
    print(f"  Done in {duration:.1f}s, {len(trace.entries)} steps")

    # ── Objective acceptance: re-read the page ourselves ──

    print("\n[2/4] Acceptance check...")
    from mio_cua.perception.perception import Perception

    # Perception reads whatever window is in front; the agent may have left
    # another one there after its last focus check.
    _ensure_foreground()
    _p = Perception(screenshot_dir=str(SCREENSHOTS_DIR))
    _probe = _p.observe()
    if "chrome" not in (_probe.active_process or "").lower():
        print(f"  ! foreground is {_probe.active_process or '?'} -- refusing to "
              f"read a transcript from the wrong window")
        reply, why, settled = "", "wrong foreground window", False
        _obs = _probe
    else:
        reply, why, _obs, settled = _settle(_p)
        print(f"  transcript: {why}{' (stable)' if settled else ' (unstable at timeout)'}")
        print(f"  stable reply observed: {'yes' if settled else 'NO -- still changing'}")

    chars = _char_count(reply)
    valid = bool(reply) and chars <= MAX_REPLY_CHARS
    print(f"  reply ({chars} chars): {reply[:200]!r}")
    print(f"  acceptance (<= {MAX_REPLY_CHARS}): {'PASS' if valid else 'FAIL'}")

    agent_claimed = any(
        e.action and e.action.type == "success" for e in trace.entries
    )

    # Did the agent claim success while the page was still streaming? Compare the
    # reply *it* saw on its final step against the settled reply we just measured.
    reply_at_claim = ""
    reply_at_claim_why = "no steps recorded"
    if trace.entries:
        reply_at_claim, reply_at_claim_why = _extract_reply(
            trace.entries[-1].obs_after or trace.entries[-1].obs_before
        )
    premature = bool(agent_claimed) and bool(reply) and reply_at_claim.strip() != reply.strip()
    if agent_claimed and premature:
        print("  !! agent claimed success before the reply settled.")

    # ── Save artifacts ──

    print("\n[3/4] Saving trace + screenshots...")
    store = TraceStore(str(TRACE_DIR / "chatgpt"))
    store.save(trace)

    for i, entry in enumerate(trace.entries):
        obs = entry.obs_before
        if obs and getattr(obs, "screenshot_path", None) and os.path.exists(obs.screenshot_path):
            import shutil
            shutil.copy2(obs.screenshot_path, str(SCREENSHOTS_DIR / f"obs_{i:03d}.png"))

    # ── Classification ──

    print("\n[4/4] Classifying failures...")
    fc = FailureClassifier()
    results = fc.classify_trace(trace, goal_keyword="介绍", goal_app="Chrome")
    summary = fc.summary(results)

    failure_report = {
        "scenario": "chatgpt_chat",
        "task": task.instruction,
        "prompt": PROMPT,
        "trace_id": trace.trace_id,
        "timestamp": trace.created_at,
        "duration_s": round(duration, 2),
        "total_steps": len(trace.entries),
        # The agent's own `success` action is advisory; this is the verdict.
        "agent_claimed_success": agent_claimed,
        "reply_stable": settled,
        "reply_chars": chars,
        "max_reply_chars": MAX_REPLY_CHARS,
        "reply_text": reply,
        # Why the extractor returned what it did. Without this a blank reply
        # (composer not found / wrong window) looked identical to a page that
        # had never answered, and the verdict gave no way to tell them apart.
        "reply_why": why,
        # What the agent saw when it stopped, versus what the page settled to.
        "reply_at_claim": reply_at_claim,
        "reply_at_claim_why": reply_at_claim_why,
        "premature_claim": premature,
        "valid": valid,
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
                    id=nd.get("id", 0), type=nd.get("type", "unknown"),
                    bbox=tuple(nd.get("bbox", [0, 0, 0, 0])), text=nd.get("text", ""),
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
            detail["quality"] = {"node_count": quality.node_count,
                                 "confidence": round(quality.confidence, 3),
                                 "is_usable": quality.is_usable,
                                 "has_search_box": quality.has_search_box}
        if entry.planner:
            detail["planner"] = {"llm_response_preview": entry.planner.llm_response[:300],
                                 "decision_state": entry.planner.decision_state}
        failure_report["step_details"].append(detail)

    report_path = TRACE_DIR / "failure_report_chatgpt.json"
    report_path.write_text(json.dumps(failure_report, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    # ── Summary ──

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"  Total steps:    {summary['total_steps']}")
    print(f"  Perception:     {summary['perception_rate']:.0%}")
    print(f"  Planner:        {summary['planner_rate']:.0%}")
    print(f"  Action:         {summary['action_rate']:.0%}")
    print(f"  Environment:    {summary['environment_rate']:.0%}")
    print(f"  Reply chars:    {chars} (limit {MAX_REPLY_CHARS})")
    print(f"  Reply stable:   {'yes' if settled else 'NO (still changing at timeout)'}")
    print(f"  Agent claimed:  {'success' if agent_claimed else 'no'}"
          + ("  <-- BEFORE the reply settled" if premature else ""))
    print(f"  VERDICT:        {'PASS' if valid else 'FAIL'}")
    if agent_claimed and not valid:
        print("  !! agent reported success but the reply did not meet the limit.")
    if not reply:
        print(f"  !! no reply extracted: {why}")
    if agent_claimed and not valid and chars == 0:
        print("  !! nothing was ever sent, or the page left the transcript area.")
    print()
    for i, r in enumerate(results):
        d = failure_report["step_details"][i]
        cat = r["category"] or "OK"
        print(f"  Step {i}: [{cat:16s}] nodes={d['scene_nodes']:3d} act={d['action_type']}")
    print()
    print(f"Report: {report_path}")
    print(f"Photos: {SCREENSHOTS_DIR}")


if __name__ == "__main__":
    main()
