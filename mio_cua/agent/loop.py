import logging
import os
import time
import uuid

from mio_cua.agent.batch import verify_action
from mio_cua.agent.diff import compute_diff
from mio_cua.automation.input_controller import InputController
from mio_cua.automation.windows import matches_target
from mio_cua.events import ObservationCreated, ActionStarted, ActionFinished, TaskFinished
from mio_cua.models.action_result import ActionResult
from mio_cua.models.task import Task, TaskResult
from mio_cua.perception.quality import assess_quality
from mio_cua.scene.memory import SceneMemory

logger = logging.getLogger(__name__)


def _keys_eq(sig, want):
    """True if a key() action sig's keys value is exactly ``want``.

    The sig looks like ``key([('keys', 'ctrl+s')])`` (real loop) or
    ``key({'keys': 'ctrl+s'})`` (older/test). Compare the exact token so
    ``ctrl+shift+n`` is not mistaken for ``ctrl+s`` (substring trap).
    """
    for sep in ("'keys', '", "'keys': '"):
        marker = "'keys'" + sep[6:]
        idx = sig.find(sep)
        if idx < 0:
            continue
        start = idx + len(sep)
        end = sig.find("'", start)
        if end < 0:
            continue
        if sig[start:end] == want:
            return True
    return False


class AgentLoop:
    def __init__(self, perception, planner, registry, safety, events,
                recover=None, config=None, history=None, controller=None,
                artifact_store=None, state_dir=None, event_sinks=None):
        self.perception = perception
        self.planner = planner
        self.registry = registry
        self.safety = safety
        self.events = events
        self.recover = recover
        self.config = config
        self.history = history
        self.controller = controller or InputController()
        self.artifact_store = artifact_store
        self.state_dir = state_dir
        # Phase 3 Runtime Event Sink bus (spec §19-§20, §32). Defaults to no
        # sinks, so existing behaviour is unchanged (zero side effects).
        self.event_sinks = list(event_sinks or [])
        self._task = None
        self._artifact_paths = []
        self._task_id = uuid.uuid4().hex[:8]
        self.scene_memory = SceneMemory()
        self._trajectory = []  # [{step, action, target, bbox, reason, obs_id, active_window, result}]

    # -- Runtime Event Sink bus (Phase 3) ---------------------------------

    def add_event_sink(self, sink) -> None:
        """Subscribe a sink (e.g. a ``Recorder``) to runtime TraceEvents."""
        self.event_sinks.append(sink)

    def emit(self, event_type: str, step: int, payload: dict, duration_ms=None) -> None:
        """Emit a runtime event to all subscribed sinks.

        Safe by design: a missing/empty sink list is a no-op, and any sink
        exception is swallowed so the agent loop never crashes because of a
        recorder/telemetry failure.
        """
        if not self.event_sinks:
            return
        try:
            from mio_cua.evaluation.schema import TraceEvent, EventType
            et = event_type if isinstance(event_type, str) else str(event_type)
            ev = TraceEvent(
                event_type=et, step=step, payload=payload, duration_ms=duration_ms,
            )
            for sink in list(self.event_sinks):
                try:
                    sink.emit(ev)
                except Exception:  # pragma: no cover - defensive
                    logger.exception("event sink %r failed", sink)
        except Exception:  # pragma: no cover - defensive
            logger.exception("emit failed")

    def _check_target_visibility(self, action, obs, task):
        """Target Visibility Invariant: target ∈ visible_candidates before select/click.

        If target is not in visible candidates, block the action and return False.
        The agent must use search/scroll/recovery instead of random selection.
        """
        # Only apply to selection actions
        if action.type not in ("click", "select_element", "type"):
            return True
        # Get target keyword from task
        keyword = (getattr(task, "metadata", None) or {}).get("keyword", "")
        if not keyword:
            return True
        # Check if target keyword is in any visible element
        scene = getattr(obs, "scene", None)
        if scene is None:
            return True
        visible_texts = []
        for n in getattr(scene, "nodes", []) or []:
            text = (getattr(n, "text", "") or "").strip()
            if text:
                visible_texts.append(text.lower())
        # Also check flat elements
        for e in getattr(obs, "elements", []) or []:
            text = (getattr(e, "text", "") or "").strip()
            if text:
                visible_texts.append(text.lower())
        # Check if keyword is visible
        keyword_lower = keyword.lower()
        target_visible = any(keyword_lower in t for t in visible_texts)
        if not target_visible:
            # Check if the action is clicking on a non-matching element
            node_id = action.params.get("element_id")
            if node_id is not None:
                # Find the element being clicked
                clicked_text = ""
                for n in getattr(scene, "nodes", []) or []:
                    if n.id == int(node_id):
                        clicked_text = (getattr(n, "text", "") or "").lower()
                        break
                for e in getattr(obs, "elements", []) or []:
                    if e.id == int(node_id):
                        clicked_text = (getattr(e, "text", "") or "").lower()
                        break
                # If clicking on something that doesn't match keyword, block it
                if clicked_text and keyword_lower not in clicked_text:
                    logger.warning("target visibility violated: clicking %r but target %r not visible",
                                    clicked_text, keyword)
                    return False
        return True

    def _make_ctx(self, obs):
        from mio_cua.tools.context import ToolContext
        self.controller.current_observation = obs
        return ToolContext(
            controller=self.controller,
            perception=self.perception,
            config=self.config,
            events=self.events,
            current_observation=obs,
        )

    def _check_context(self, task, obs):
        """Verify target_context ⊆ observation.context.

        On mismatch: focus the target window, re-observe, and confirm the
        foreground really is the target. Focus is confirmed by process name as
        well as title — an Edge window's title is its page title ("MIO·HUB —
        任务总线") and never contains "edge", so title-only matching can never
        verify focus for a browser.

        Returns (obs, context_ok) - possibly updated observation after refocus.
        """
        from mio_cua.automation.windows import get_active_window, matches_target

        target = getattr(task, "target_context", None) or {}
        if not target:
            return obs, True

        match_target = target.get("window", "") or target.get("app", "")
        if not match_target:
            return obs, True

        obs_title = getattr(obs, "active_window", "") or ""
        obs_proc = getattr(obs, "active_process", None)
        if matches_target(match_target, obs_title, obs_proc):
            return obs, True

        # Mismatch: focus target window
        logger.info("context mismatch: target=%r active=%r/%r, focusing",
                    match_target, obs_title, obs_proc)
        for attempt in range(5):
            try:
                self.registry.call("focus_window", {"title": match_target}, self._make_ctx(obs))
            except Exception:
                logger.debug("focus_window raised", exc_info=True)
            time.sleep(1.5 + attempt * 0.5)
            # Verify the foreground really moved before paying for a re-observe.
            if not matches_target(match_target):
                logger.debug("focus attempt %d: window=%r, expected=%r",
                             attempt + 1, get_active_window(), match_target)
                continue
            # Re-observe after verified focus
            obs = self.perception.observe()
            if obs is None:
                logger.warning("re-observe returned no observation (attempt %d)", attempt + 1)
                continue
            self.events.publish(ObservationCreated(obs))
            active = getattr(obs, "active_window", "") or ""
            # Judge by the observation's OWN title+process. Do not also require
            # the live foreground to match: for a browser the title never names
            # the app, so a conjunctive check can never pass (it silently turned
            # every attempt into a re-observe until the run timed out).
            if matches_target(match_target, active, getattr(obs, "active_process", None)):
                scene = getattr(obs, "scene", None)
                nodes = len(getattr(scene, "nodes", [])) if scene else 0
                if nodes > 10:
                    logger.info("context aligned: active=%r proc=%r nodes=%d (attempt %d)",
                                active, getattr(obs, "active_process", None), nodes, attempt + 1)
                    break
                logger.warning("context aligned but scene sparse: active=%r nodes=%d",
                               active, nodes)
            else:
                logger.warning("context check failed: active=%r proc=%r (attempt %d)",
                               active, getattr(obs, "active_process", None), attempt + 1)
        else:
            logger.warning("context still mismatched after focus: active=%r",
                           get_active_window())
            return obs, False
        return obs, True

    def _detect_obstruction(self, obs, task):
        """High-confidence obstruction signals that warrant *recovery* (a
        deterministic fix), not a blind retry.

        Returns a failure-mode string (``"context_menu"``) or ``None``.
        """
        scene = getattr(obs, "scene", None)
        if scene is None:
            return None
        for n in getattr(scene, "nodes", []) or []:
            role = (getattr(n, "role", "") or "").lower()
            typ = (getattr(n, "type", "") or "").lower()
            if role in ("menu", "contextmenu") or typ == "contextmenu":
                return "context_menu"
        return None

    def _extract_target_info(self, action, obs):
        """Extract target element info from action + observation for trajectory logging."""
        info = {"target": None, "bbox": None, "reason": None}
        scene = getattr(obs, "scene", None)
        if scene is None:
            return info
        node_id = action.params.get("element_id")
        if node_id is not None:
            node = None
            for n in getattr(scene, "nodes", []) or []:
                if n.id == int(node_id):
                    node = n
                    break
            if node:
                info["target"] = node.semantic or node.text or f"node_{node_id}"
                info["bbox"] = node.bbox
        # Extract thought/reason from plan if available
        if hasattr(action, "thought"):
            info["reason"] = action.thought
        return info

    def _extract_sidebar_candidates(self, obs):
        """Extract visible chat/group names from left sidebar (left 35% of active window).

        Entries are returned deterministic and in visual top-to-bottom order.
        The old ``list(set(...))`` threw the order away, so with two entries of
        the same name ("另一个张三", a repeated group) the one the planner picks
        was arbitrary -- and node order is not on-screen order anyway.
        """
        items = []          # (y, x, text)
        active_window = getattr(obs, "active_window", "") or ""
        # Find the active window's bbox from scene
        from mio_cua.automation.windows import frame_bbox
        scene = getattr(obs, "scene", None)
        window_bbox = frame_bbox(getattr(scene, "nodes", None)) if scene else None
        sidebar_right = None
# If we found the window, define sidebar as left 50% of window
        if scene:
            if window_bbox:
                wx, wy, ww, wh = window_bbox
                sidebar_right = wx + int(ww * 0.5)
            # Scene nodes
            for n in getattr(scene, "nodes", []) or []:
                bbox = getattr(n, "bbox", None)
                text = (getattr(n, "text", "") or "").strip()
                if bbox and len(bbox) >= 2 and sidebar_right is not None \
                        and bbox[0] < sidebar_right and text:
                    items.append((bbox[1], bbox[0], text))
        # Fallback: absolute x < 400 (for windows at left of screen)
        if not window_bbox:
            for n in getattr(obs.scene, "nodes", []) or []:
                bbox = getattr(n, "bbox", None)
                text = (getattr(n, "text", "") or "").strip()
                if bbox and len(bbox) >= 2 and bbox[0] < 400 and text:
                    items.append((bbox[1], bbox[0], text))
        # Flat elements fallback
        for e in getattr(obs, "elements", []) or []:
            bbox = getattr(e, "bbox", None)
            text = (getattr(e, "text", "") or "").strip()
            if bbox and len(bbox) >= 2 and text:
                # Check if in sidebar region
                in_sidebar = False
                if window_bbox:
                    wx, _, ww, _ = window_bbox
                    sidebar_right = wx + int(ww * 0.5)
                    if bbox[0] < sidebar_right:
                        in_sidebar = True
                elif bbox[0] < 400:
                    in_sidebar = True
                if in_sidebar:
                    items.append((bbox[1], bbox[0], text))
        items.sort(key=lambda it: (it[0], it[1]))
        seen, out = set(), []
        for _y, _x, text in items:
            if text in seen:
                continue
            seen.add(text)
            out.append(text)
        return out

    def _save_artifact(self, obs, action, result):
        if self.artifact_store is None:
            return
        p = self.artifact_store.save_artifact(obs=obs, action=action, result=result,
                                                task_id=self._task_id)
        self._artifact_paths.append(str(p))

    def _save_state(self, obs, step):
        if self.state_dir is None:
            return
        from mio_cua.memory.state import TaskState, state_path
        shot = obs.screenshot_path if obs else ""
        TaskState(state_path(self.state_dir, self._task_id)).save(
            task_id=self._task_id,
            instruction=self._task.instruction if self._task else "",
            step=step,
            screenshot=shot,
        )

    def _prune_artifacts(self):
        if self.artifact_store is None:
            return
        limit = getattr(self.config, "artifact_max_bytes", 200 * 1024 * 1024)
        try:
            freed = self.artifact_store.prune(limit)
            if freed:
                logger.info("pruned %d bytes of old artifacts", freed)
        except Exception as e:
            logger.warning("artifact prune failed: %s", e)

    def run(self, task: Task) -> TaskResult:
        start = time.time()
        self._task = task
        self.safety.start()
        steps = 0
        finished_status = None
        finished_summary = ""
        terminal = "RUNNING"
        try:
            from collections import deque
            from mio_cua.agent.expected import ExpectedVerifier
            prev = None
            no_change = 0
            repeat_count = 0
            self._recent_sigs = deque(maxlen=8)
            self._verifier = ExpectedVerifier()
            self._pending_verify = None  # (node_id, expected, prev_scene) awaiting the next observation
            self._batch_failed = None
            while not self.safety.should_stop():
                _t = time.time(); print(f"[diag] observe start (step {steps})", flush=True)
                obs = self.perception.observe()
                print(f"[diag] observe done ({time.time()-_t:.1f}s)", flush=True)
                self.events.publish(ObservationCreated(obs))
                self._save_state(obs, steps)
                self.scene_memory.push(getattr(obs, "scene", None))
                # Context invariant: target_context ⊆ observation.context
                obs, context_ok = self._check_context(task, obs)
                if not context_ok:
                    hints = ["目标应用窗口未找到或无法聚焦，请检查目标应用是否已安装并运行。"]
                    plan = self.planner.plan(task, obs, compute_diff(None, obs),
                                            self.registry.schemas(), history=self.history, hints=hints)
                    if plan.actions:
                        ctx = self._make_ctx(obs)
                        for action in plan.actions:
                            if action.type in ("success", "fail"):
                                break
                            try:
                                self.registry.call(action.type, action.params, ctx)
                            except Exception:
                                pass
                        # After focus action, continue to next iteration to re-observe
                        steps += 1
                        continue
                    break
                # Obstruction recovery: a stray context menu blocks every click.
                # Dismiss it deterministically (Esc) before replanning -- this is
                # *recovery*, not a blind retry.
                obstruction = self._detect_obstruction(obs, task)
                if obstruction == "context_menu":
                    logger.info("obstruction: context menu detected, dismissing with Esc")
                    try:
                        self.registry.call("key", {"keys": "esc"}, self._make_ctx(obs))
                    except Exception:
                        pass
                    time.sleep(0.3)
                    if self._trajectory:
                        self._trajectory[-1]["recovery"] = "context_menu:dismissed"
                    continue
                # Perception quality gate: check if scene graph is usable
                quality = assess_quality(getattr(obs, "scene", None))
                if not quality.is_usable:
                    hints = [
                        "OBSERVATION QUALITY: low visibility. "
                        f"Visible elements: {quality.node_count} ({quality.interactive_count} interactive). "
                        "Actions: scroll to reveal more content, or use search to find targets. "
                        "Do NOT click on elements you cannot see."
                    ]
                    logger.warning("perception quality insufficient at step %d: %s", steps, quality.reason)
                else:
                    hints = []
                diff = compute_diff(prev, obs)
                if prev is not None and not diff.changes:
                    no_change += 1
                else:
                    no_change = 0
                if self._pending_verify is not None:
                    vh = self._verify_pending(obs)
                    if vh:
                        hints.append(vh)
                    self._pending_verify = None
                mem_summary = self.scene_memory.summarize(
                    recent_actions=[h["type"] for h in (self.history.recent(6) if self.history else [])]
                    if self.history else None,
                )
                if mem_summary:
                    hints.append("MEMORY (what you have already seen/done):\n" + mem_summary +
                                "\nUse this to continue the task -- do not re-read or re-open what you already saw.")
                if no_change >= 2:
                    hints.append('the screen did not change after your recent actions — the last action had no visible effect. Do NOT repeat it. To confirm a dialog, call key(keys="enter") or click the Save/OK button.')
                confirm_hint = self._confirm_hint()
                if confirm_hint:
                    hints.append(confirm_hint)
                rename_hint = self._rename_hint()
                if rename_hint:
                    hints.append(rename_hint)
                finish_hint = self._completion_hint(no_change)
                if finish_hint:
                    hints.append(finish_hint)
                if self._batch_failed:
                    hints.append("GUIDANCE: the last batch was aborted because "
                                f"{self._batch_failed}; re-inspect the screen "
                                "and pick a fresh action, do NOT blindly repeat.")
                    self._batch_failed = None
                if len(self._recent_sigs) >= 4 and self._recent_sigs.count(self._recent_sigs[-1]) >= 4:
                    hints.append(f"you have called `{self._recent_sigs[-1]}` repeatedly with no effect. STOP repeating it and choose a different action now.")
                if hints:
                    logger.debug("hints@%d: %s", steps, " | ".join(hints))
                _t = time.time()
                plan = self.planner.plan(task, obs, diff, self.registry.schemas(), history=self.history, hints=hints)
                print(f"[diag] planner done ({time.time()-_t:.1f}s) actions={len(plan.actions)} thought={getattr(plan, 'thought', '')[:160]!r}", flush=True)
                if not plan.actions:
                    finished_status = "FAIL"
                    finished_summary = (
                        f"planner returned 0 actions "
                        f"(thought={getattr(plan, 'thought', '')!r})"
                    )
                    break
                ctx = self._make_ctx(obs)
                config_batch_limit = getattr(self.config, "batch_limit", 3) if self.config else 3
                config_batch_verify = getattr(self.config, "batch_verify", True) if self.config else True
                batch_executed = 0
                light_base = obs
                for i, action in enumerate(plan.actions):
                    if batch_executed >= config_batch_limit or self.safety.should_stop():
                        break
                    # Target Visibility Invariant
                    if not self._check_target_visibility(action, obs, task):
                        logger.warning("action blocked by target visibility: %s(%s)", action.type, action.params)
                        hints.append(
                            f"TARGET NOT VISIBLE: the target '{getattr(task, 'metadata', {}).get('keyword', '?')}' "
                            f"is not in the current visible candidates. Do NOT click on other items. "
                            f"Instead, use scroll to find the target, or use search if available."
                        )
                        # Re-plan with the hint
                        plan = self.planner.plan(task, obs, diff, self.registry.schemas(),
                                                history=self.history, hints=hints)
                        if not plan.actions:
                            break
                        continue
                    # Action Guard: block redundant focus_window
                    if action.type == "focus_window":
                        focus_title = (action.params.get("title") or "").lower()
                        current_window = (getattr(obs, "active_window", "") or "").lower()
                        if focus_title and focus_title in current_window:
                            logger.info("action guard: skip focus_window('%s'), already active", focus_title)
                            hints.append(
                                f"ALREADY FOCUSED: 当前窗口已是 '{getattr(obs, 'active_window', '')}'. "
                                f"不要再调用 focus_window. 直接执行任务."
                            )
                            plan = self.planner.plan(task, obs, diff, self.registry.schemas(),
                                                    history=self.history, hints=hints)
                            if not plan.actions:
                                break
                            continue
                    # Target Discovery Guard: warn about wrong clicks when target not visible
                    if action.type == "click":
                        keyword = (getattr(task, "metadata", None) or {}).get("keyword", "")
                        if keyword:
                            clicked_id = action.params.get("id")
                            clicked_node = None
                            for n in (obs.scene.nodes if obs.scene else []):
                                if n.id == clicked_id:
                                    clicked_node = n
                                    break
                            if clicked_node:
                                clicked_text = (clicked_node.semantic or clicked_node.text or "").strip()
                                if keyword.lower() not in clicked_text.lower():
                                    # Check if search affordance exists
                                    has_search = False
                                    for a in (getattr(obs.scene, "affordances", []) if obs.scene else []):
                                        if a.params.get("purpose") == "search":
                                            has_search = True
                                            break
                                    search_hint = " 有搜索框，用搜索功能." if has_search else ""
                                    hints.append(
                                        f"TARGET MISMATCH: 你点击了 '{clicked_text}'，但目标是 '{keyword}'. "
                                        f"不要点击不匹配的元素.{search_hint}"
                                    )
                    self.events.publish(ActionStarted(action))
                    ctx.current_action_id = action.id
                    try:
                        result = self.registry.call(action.type, action.params, ctx)
                    except Exception as e:
                        # Grounding ambiguity must replan (not blind-retry);
                        # other errors stay retryable so Recover can act.
                        retryable = not getattr(e, "ambiguous", False)
                        result = ActionResult(action.id, success=False, message=str(e), retryable=retryable)
                    if not result.success and result.retryable and self.recover is not None:
                        result = self.recover(action, result, ctx)
                    self._save_artifact(obs, action, result)
                    self.events.publish(ActionFinished(result))
                    if self.history is not None:
                        self.history.record(action.id, action.type, result.success, result.message)
                    # Trajectory logging
                    target_info = self._extract_target_info(action, obs)
                    self._trajectory.append({
                        "step": steps,
                        "action": action.type,
                        "params": action.params,
                        "target": target_info.get("target"),
                        "bbox": target_info.get("bbox"),
                        "reason": target_info.get("reason"),
                        "obs_id": str(id(obs)),
                        "active_window": getattr(obs, "active_window", ""),
                        "result_success": result.success,
                        "result_msg": (result.message or "")[:200],
                    })
                    # Post-action context verify
                    target = getattr(task, "target_context", None) or {}
                    target_app = target.get("app") or target.get("window", "")
                    if target_app and action.type not in ("success", "fail", "focus_window"):
                        try:
                            _t = time.time(); print("[diag] post-action observe start", flush=True)
                            post_obs = self.perception.observe()
                            print(f"[diag] post-action observe done ({time.time()-_t:.1f}s)", flush=True)
                            post_active = getattr(post_obs, "active_window", "") or ""
                            post_proc = getattr(post_obs, "active_process", None)
                            # Title-only substring check ("Edge" in title) flags
                            # a violation whenever the Edge window is showing
                            # anything but a title containing "Edge" -- the
                            # taskhub page is titled "MIO·HUB — 任务总线",
                            # so this used to fire a pointless focus+re-observe
                            # after EVERY action. Match on the owning process.
                            if not matches_target(target_app, post_active, post_proc):
                                logger.warning(
                                    "post-action context violated: expected=%r got=%r (process=%r) after %s",
                                    target_app, post_active, post_proc, action.type)
                                self._trajectory[-1]["context_violated"] = True
                                self._trajectory[-1]["post_active"] = post_active
                                self._trajectory[-1]["post_process"] = post_proc
                                # Recovery: focus target
                                try:
                                    self.registry.call("focus_window", {"title": target_app}, self._make_ctx(post_obs))
                                except Exception:
                                    pass
                                time.sleep(0.5)
                                # Re-observe
                                _t = time.time(); print("[diag] re-observe start", flush=True)
                                obs = self.perception.observe()
                                print(f"[diag] re-observe done ({time.time()-_t:.1f}s)", flush=True)
                                self.events.publish(ObservationCreated(obs))
                                self._trajectory[-1]["recovery_active"] = getattr(obs, "active_window", "")
                        except Exception:
                            pass
                    # Scroll Progress Verify
                    if action.type == "scroll":
                        try:
                            post_obs = self.perception.observe()
                            keyword = (getattr(task, "metadata", None) or {}).get("keyword", "")
                            if keyword:
                                prev_candidates = self._extract_sidebar_candidates(obs)
                                new_candidates = self._extract_sidebar_candidates(post_obs)
                                changed = set(new_candidates) != set(prev_candidates)
                                target_visible = any(keyword.lower() in c.lower() for c in new_candidates)
                                self._trajectory[-1]["scroll_progress"] = {
                                    "prev_count": len(prev_candidates),
                                    "new_count": len(new_candidates),
                                    "changed": changed,
                                    "target_visible": target_visible,
                                }
                                if target_visible:
                                    logger.info("scroll progress: target %r now visible", keyword)
                                elif not changed:
                                    logger.warning("scroll progress: candidates unchanged after %s", action.params)
                                    hints.append(
                                        f"SCROLL STALLED: scrolling {action.params.get('direction')} "
                                        f"did not reveal new candidates. Try the opposite direction, "
                                        f"or use search if available."
                                    )
                                else:
                                    logger.info("scroll progress: %d -> %d candidates, target not yet visible",
                                                len(prev_candidates), len(new_candidates))
                        except Exception:
                            pass
                    self.safety.record_step()
                    steps += 1
                    if not result.success:
                        # action failed (recover exhausted) -> abort the whole batch
                        self._batch_failed = result.message or "action failed"
                        break
                    if action.type == "success":
                        blocker = self._unconfirmed_edit()
                        if blocker:
                            # hard guard: an element_id-less type (rename box /
                            # filename field) was not confirmed with Enter, so a
                            # success() would claim an edit that never applied.
                            hints.append(blocker)
                            self._save_artifact(obs, action, result)
                            self.events.publish(ActionFinished(ActionResult(
                                action.id, False, blocker, retryable=True)))
                            if self.history is not None:
                                self.history.record(action.id, action.type, False, blocker)
                            self.safety.record_step()
                            steps += 1
                            continue
                        finished_status = "SUCCESS"
                        finished_summary = str(action.params.get("result", ""))
                        break
                    if action.type == "fail":
                        finished_status = "FAIL"
                        finished_summary = str(action.params.get("reason", ""))
                        break
                    if action.type not in ("success", "fail"):
                        sig = f"{action.type}({sorted(action.params.items())})"
                        if self._recent_sigs and self._recent_sigs[-1] == sig:
                            repeat_count += 1
                        else:
                            repeat_count = 1
                        self._recent_sigs.append(sig)
                        if repeat_count >= 6:
                            finished_status = "FAIL"
                            finished_summary = f"stuck: repeated {sig} {repeat_count} times with no effect"
                            break
                    batch_executed += 1
                    # Capture the expected on-screen change (clicks that map to an
                    # affordance, or a focus_window whose target we can re-check).
                    expected = None
                    pending = None
                    if action.type == "click":
                        pending = self._capture_expected(obs, action)
                        expected = pending[1] if pending else None
                    elif action.type == "focus_window":
                        title = (action.params.get("title") or "").strip()
                        if title:
                            pending = (None, {"window_title": title}, obs)
                    light_observe = getattr(self.perception, "observe_light", None)
                    has_successor = (i + 1 < len(plan.actions)) and (batch_executed < config_batch_limit)
                    _needs_full = bool(expected) and any(
                        k in expected for k in ("state_toggle", "window_title"))

                    # Defer to the next full observation when the expectation needs
                    # a UIA-backed frame (toggle state / window title), at the batch
                    # tail, or when verification is disabled / no light path exists.
                    if action.type == "click" and (
                        _needs_full or not has_successor
                        or not config_batch_verify or light_observe is None
                    ):
                        if _needs_full or pending is not None:
                            self._pending_verify = pending
                        break
                    # In-batch light verification (click w/ display|text expectation,
                    # or any click w/ no expectation -> OCR-layer screen-diff).
                    if action.type == "click" and light_observe is not None:
                        light = light_observe()
                        ok, detail = verify_action(
                            light_base, light, action, expected,
                            node_id=action.params.get("element_id"),
                        )
                        if not ok:
                            if self.history is not None:
                                self.history.record(action.id, action.type, False, f"verify: {detail}")
                            self._batch_failed = detail
                            break
                        light_base = light
                    elif action.type == "focus_window" and pending is not None:
                        # Re-check window focus on the next full observation, but
                        # keep running the rest of the batch (focus is cheap).
                        self._pending_verify = pending
                if finished_status in ("SUCCESS", "FAIL"):
                    break
                prev = obs
        except Exception as e:
            finished_status = "FAIL"
            finished_summary = f"loop error: {e}"
        finally:
            # capture status BEFORE stopping so stop() doesn't flip it to ABORTED
            terminal = self.safety.status()
            self.safety.stop()

        status = finished_status or terminal
        if status == "RUNNING":
            status = "FAIL"
        self._prune_artifacts()
        result = TaskResult(
            status=status,
            summary=finished_summary,
            task_id=self._task_id,
            steps=steps,
            duration=time.time() - start,
            artifacts=self._artifact_paths,
        )
        self.events.publish(TaskFinished(result))
        # Save trajectory for debugging
        if self._trajectory and self.state_dir:
            import json as _json
            os.makedirs(self.state_dir, exist_ok=True)
            traj_path = os.path.join(self.state_dir, f"trajectory_{self._task_id}.json")
            with open(traj_path, "w", encoding="utf-8") as f:
                _json.dump(self._trajectory, f, ensure_ascii=False, indent=2)
            logger.info("trajectory saved: %s (%d entries)", traj_path, len(self._trajectory))
        return result

    def _capture_expected(self, obs, action):
        """Record the clicked node's expected screen change for verification."""
        scene = getattr(obs, "scene", None)
        if scene is None:
            return None
        node_id = action.params.get("element_id")
        if node_id is None:
            return None
        aff = scene.affordance_for(int(node_id), "click")
        if aff is None or not aff.expected:
            return None
        return (int(node_id), dict(aff.expected), scene)

    def _verify_pending(self, obs):
        """Check whether the previous action produced its expected change."""
        node_id, expected, prev_scene = self._pending_verify
        if "window_title" in expected:
            ok, detail = self._verifier.verify(
                None, None, expected, curr_active_window=getattr(obs, "active_window", ""))
            if ok:
                return None
            return (f"VERIFICATION: after the window action the active window is "
                    f"{getattr(obs, 'active_window', '')!r} but expected to match "
                    f"{expected['window_title']!r}. The target window may not be "
                    f"focused -- do NOT assume success; re-focus or pick another action.")
        curr_scene = getattr(obs, "scene", None)
        if curr_scene is None:
            return None
        ok, detail = self._verifier.verify(prev_scene, curr_scene, expected, node_id=node_id)
        if ok:
            return None
        return (f"VERIFICATION: your last action on node {node_id} did not have the "
                f"expected effect ({detail}). It likely missed or the target changed. "
                f"Do NOT repeat it blindly -- re-inspect and pick a fresh target.")

    def _unconfirmed_edit(self):
        """A rename/filename type (type WITHOUT element_id) that has NOT been
        confirmed with Enter. success() must be blocked then, or the agent
        claims an edit that never applied (folder/file name unchanged)."""
        sigs = list(getattr(self, "_recent_sigs", None) or [])
        typed = [s for s in sigs if s.startswith("type(") and "element_id" not in s]
        if not typed:
            return None
        if any(self._is_confirming_action(s) for s in sigs):
            return None
        return ("BLOCKED: you typed a name but never pressed `enter` to apply it "
                "-- the edit is NOT saved. Call `key(keys=\"enter\")` to confirm, "
                "then call `success`.")

    def _rename_hint(self):
        """If the agent pressed ctrl+shift+n (created a new folder) but has not
        typed a name for it, the folder stays '新建文件夹' and the task is not
        done. Tell it to type the name (type WITHOUT element_id -- the rename
        box has focus)."""
        sigs = list(getattr(self, "_recent_sigs", None) or [])
        if not sigs:
            return None
        created = any("ctrl+shift+n" in s for s in sigs[-4:])
        if not created:
            return None
        if any(s.startswith("type(") for s in sigs[-4:]):
            return None
        return ("You created a new folder (ctrl+shift+n) but have NOT typed its "
                "name. Its name is selected and the rename box has focus -- call "
                "`type` WITHOUT element_id (e.g. `type(text=\"smoke_demo_folder\")`) "
                "to name it, then press `enter`.")

    def _confirm_hint(self):
        """If the agent typed WITHOUT an element_id (a focused rename box or
        filename field -- the explorer/filename case) and has not pressed Enter
        to confirm, the edit is still pending. Tell it to press Enter instead
        of re-typing or moving on. The classic explorer failure: type the
        folder name, never press Enter, call success.

        Types WITH an element_id (e.g. notepad body) do not need Enter, so we
        only react to element_id-less types to avoid false positives.
        """
        sigs = list(getattr(self, "_recent_sigs", None) or [])
        if not sigs:
            return None
        typed_without_target = [s for s in sigs
                                if s.startswith("type(") and "element_id" not in s]
        if not typed_without_target:
            return None
        # ...and no Enter/Save confirmation after the latest such type
        if any(self._is_confirming_action(s) for s in sigs[-3:]):
            return None
        return ("You typed into a rename/filename box (type without element_id) "
                "but have NOT pressed `enter` to confirm it -- the change is NOT "
                "applied until `enter`. Call `key(keys=\"enter\")` now, then the "
                "task is done.")

    def _completion_hint(self, no_change):
        """Hint the agent to finish when it has done the closing steps but
        keeps verifying instead of calling success (task completed but
        status=TIMEOUT).

        Requires a *confirming* action (Enter / Save) reasonably recent AND the
        screen to have settled (no_change >= 1). Not just any type: typing
        without Enter leaves the edit unconfirmed, so that alone is not
        completion (see _confirm_hint). A confirming action later in the
        trailing history means a save/rename was applied.
        """
        if no_change < 1:
            return None
        sigs = list(getattr(self, "_recent_sigs", None) or [])
        if len(sigs) < 2:
            return None
        confirmed = [s for s in sigs if self._is_confirming_action(s)]
        if not confirmed:
            return None
        # The confirming action should not be buried too far behind unrelated work.
        last_index = max(i for i, s in enumerate(sigs) if self._is_confirming_action(s))
        if len(sigs) - 1 - last_index > 2:
            return None
        return ("The screen has settled and you already pressed Enter / Save to "
                "apply the change. If the task's goal is met, STOP and call "
                "`success` with a summary now -- do not keep acting.")

    @staticmethod
    def _is_confirming_action(sig):
        """Actions that CONFIRM a save/rename: Enter, Save click, Ctrl+S."""
        if sig.startswith("key("):
            return any(_keys_eq(sig, k) for k in ("enter", "ctrl+s"))
        if sig.startswith("click("):
            return "Save" in sig or "保存" in sig
        return False
