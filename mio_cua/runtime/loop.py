"""AgentLoopV2 — Agent Runtime v2 orchestration.

This replaces the v1 if-else invariants with the five composable loops driven
by the runtime components:

    Goal -> Belief/State -> Perception(->Affordance) -> Planner
         -> Action -> Execute -> Observe -> Verify(Progress) -> Recovery

It subclasses ``AgentLoop`` so it reuses all the proven machinery
(``_make_ctx``, ``_save_artifact``, ``_save_state``, trajectory logging,
success/fail/timeout handling, confirm/rename guards). The difference is that
the *decisions* — context alignment, target visibility, scroll progress,
focus recovery — are made by ``BeliefState`` / ``ProgressEvaluator`` /
``RecoveryManager`` instead of inline branches, so they can be extended as
policies rather than patched as heuristics.
"""

import logging
import os
import time
from collections import deque

from mio_cua.agent.batch import verify_action
from mio_cua.agent.diff import compute_diff
from mio_cua.agent.expected import ExpectedVerifier
from mio_cua.agent.loop import AgentLoop
from mio_cua.events import ObservationCreated, ActionStarted, ActionFinished, TaskFinished
from mio_cua.models.action_result import ActionResult
from mio_cua.models.task import Task, TaskResult
from mio_cua.runtime.belief import BeliefState
from mio_cua.runtime.observation import RuntimeObservation
from mio_cua.runtime.progress import ProgressEvaluator
from mio_cua.runtime.recovery import RecoveryManager

logger = logging.getLogger(__name__)


class AgentLoopV2(AgentLoop):
    def run(self, task: Task) -> TaskResult:
        start = time.time()
        self._task = task
        self.safety.start()
        # Phase 3: announce the task to any subscribed event sinks (spec §32).
        self.emit("task_started", 0, {
            "goal": getattr(task, "instruction", ""),
            "task_id": self._task_id,
            "target_context": getattr(task, "target_context", None) or {},
        })
        steps = 0
        finished_status = None
        finished_summary = ""
        terminal = "RUNNING"

        belief = BeliefState(getattr(task, "target_context", None) or {})
        progress = ProgressEvaluator()
        recovery = RecoveryManager(
            registry=self.registry,
            controller=self.controller,
            perception=self.perception,
            events=self.events,
            enabled=getattr(self.config, "enable_recovery", True),
        )

        try:
            prev = None
            no_change = 0
            repeat_count = 0
            self._recent_sigs = deque(maxlen=8)
            self._verifier = ExpectedVerifier()
            self._pending_verify = None
            self._batch_failed = None

            target = belief.target_context
            target_app = target.get("app") or target.get("window", "")
            keyword = target.get("keyword", "")

            while not self.safety.should_stop():
                obs = self.perception.observe()
                self.controller.current_observation = obs
                self.events.publish(ObservationCreated(obs))
                self.emit("observation", steps, {"observation": obs})
                self._save_state(obs, steps)
                self.scene_memory.push(getattr(obs, "scene", None))

                robs = RuntimeObservation.from_obs(obs, belief.target_context)
                belief.update(robs)
                self.emit("belief_updated", steps, {"belief": belief, "runtime_obs": robs})

                hints = []

                # --- Context invariant (via Recovery) ---
                if not belief.context_matches:
                    self.emit("recovery_started", steps, {
                        "recovery": {"reason": "context_mismatch",
                                     "strategy": "focus_target",
                                     "previous_action": "observe"},
                    })
                    focused = False
                    for _attempt in range(3):
                        ctx = self._make_ctx(obs)
                        recovery.focus_target(target_app, ctx)
                        time.sleep(0.6)
                        obs = self.perception.observe()
                        self.events.publish(ObservationCreated(obs))
                        robs = RuntimeObservation.from_obs(obs, belief.target_context)
                        belief.update(robs)
                        if belief.context_matches:
                            focused = True
                            break
                    if not focused:
                        recovery.apply_recovery("context_mismatch", belief, robs, self._make_ctx(obs))
                        hints += recovery.policy_for("context_mismatch", belief, robs)
                        plan = self.planner.plan(
                            task, obs, compute_diff(None, obs),
                            self.registry.schemas(), history=self.history, hints=hints,
                        )
                        self.emit("plan_created", steps, {"plan": plan, "runtime_obs": robs})
                        if plan.actions:
                            ctx = self._make_ctx(obs)
                            for action in plan.actions:
                                if action.type in ("success", "fail"):
                                    break
                                try:
                                    self.registry.call(action.type, action.params, ctx)
                                except Exception:
                                    pass
                        self.emit("recovery_completed", steps, {
                            "recovery": {"reason": "context_mismatch",
                                         "success": bool(plan.actions)},
                        })
                        break

                diff = compute_diff(prev, obs)
                if prev is not None and not diff.changes:
                    no_change += 1
                else:
                    no_change = 0

                if self._pending_verify is not None and getattr(self.config, "enable_verification", True):
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
                    hints.append("the screen did not change after your recent actions — the last action had no visible effect. Do NOT repeat it.")

                # Grounded affordance hints (from Perception, not LLM guesses).
                if robs.chat_list_region is not None:
                    r = robs.chat_list_region
                    hints.append(
                        f"AFFORDANCE: the chat/list area is a scrollable region at bbox {r}. "
                        f"Scrolling there reveals more chats/groups; the runtime will target that region."
                    )
                if robs.search_box is not None:
                    s = robs.search_box.bbox
                    hints.append(
                        f"AFFORDANCE: a search box is at bbox {s}. To jump directly to the target, "
                        f"click it at x={s[0] + s[2] // 2} y={s[1] + s[3] // 2}, then type the keyword and press enter."
                    )
                hints.append(
                    "To open a chat, CLICK A SIDEBAR CHAT ITEM (a leaf node in the chat list), "
                    "not the window container/group node."
                )
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

                plan = self.planner.plan(
                    task, obs, diff, self.registry.schemas(), history=self.history, hints=hints
                )
                self.emit("plan_created", steps, {"plan": plan, "runtime_obs": robs})
                if not plan.actions:
                    break

                ctx = self._make_ctx(obs)
                config_batch_limit = getattr(self.config, "batch_limit", 3) if self.config else 3
                batch_executed = 0
                light_base = obs

                for i, action in enumerate(plan.actions):
                    if batch_executed >= config_batch_limit or self.safety.should_stop():
                        break

                    # --- Click-coordinate guard: reject raw x/y outside window ---
                    if action.type == "click" and "element_id" not in action.params \
                            and "x" in action.params and "y" in action.params:
                        wb = robs.window_bbox
                        x, y = action.params["x"], action.params["y"]
                        inside = wb and (wb[0] <= x <= wb[0] + wb[2] and wb[1] <= y <= wb[1] + wb[3])
                        if not inside:
                            logger.warning("v2 click coords outside target window: (%s,%s) not in %r", x, y, wb)
                            hints.append(
                                "Your click used raw x/y coordinates that fall OUTSIDE the target window. "
                                "Always click by element_id from the 'Left sidebar (chat list)' / 'Scene' list "
                                "instead of guessing coordinates."
                            )
                            self._trajectory.append({
                                "step": steps, "action": action.type, "params": action.params,
                                "target": None, "bbox": None, "reason": "blocked: click outside window",
                                "obs_id": robs.obs_id, "active_window": robs.context,
                                "result_success": False, "result_msg": "click outside window blocked",
                                "target_violated": True,
                            })
                            plan = self.planner.plan(
                                task, obs, diff, self.registry.schemas(),
                                history=self.history, hints=hints,
                            )
                            self.emit("plan_created", steps, {"plan": plan, "runtime_obs": robs})
                            if not plan.actions:
                                break
                            continue

                    # --- Target Visibility invariant (via Belief) ---
                    if action.type in ("click", "select_element", "type") and not belief.target_visible:
                        if self._clicking_non_matching(action, robs, keyword):
                            logger.warning("v2 target visibility: blocking %s on non-matching element", action.type)
                            recovery.apply_recovery("target_invisible", belief, robs, self._make_ctx(obs))
                            hints += recovery.policy_for("target_invisible", belief, robs)
                            self._trajectory.append({
                                "step": steps, "action": action.type, "params": action.params,
                                "target": None, "bbox": None, "reason": "blocked: target invisible",
                                "obs_id": robs.obs_id, "active_window": robs.context,
                                "result_success": False, "result_msg": "target visibility blocked",
                                "target_violated": True,
                            })
                            self.emit("recovery_started", steps, {
                                "recovery": {"reason": "target_invisible",
                                             "strategy": "replan",
                                             "previous_action": action.type},
                            })
                            plan = self.planner.plan(
                                task, obs, diff, self.registry.schemas(),
                                history=self.history, hints=hints,
                            )
                            self.emit("plan_created", steps, {"plan": plan, "runtime_obs": robs})
                            if not plan.actions:
                                self.emit("recovery_completed", steps, {
                                    "recovery": {"reason": "target_invisible", "success": False},
                                })
                                break
                            self.emit("recovery_completed", steps, {
                                "recovery": {"reason": "target_invisible", "success": True},
                            })
                            continue

                    # --- Scroll direction adaptation (and grounded region) ---
                    if action.type == "scroll":
                        direction = self._pick_scroll_direction(action, belief)
                        action.params["direction"] = direction
                        if robs.chat_list_region is not None:
                            action.params["region"] = robs.chat_list_region

                    self.emit("action_started", steps, {"action": action})
                    self.events.publish(ActionStarted(action))
                    ctx.current_action_id = action.id
                    try:
                        result = self.registry.call(action.type, action.params, ctx)
                    except Exception as e:
                        result = ActionResult(action.id, success=False, message=str(e), retryable=True)
                    if not result.success and result.retryable and self.recover is not None:
                        result = self.recover(action, result, ctx)
                    self._save_artifact(obs, action, result)
                    self.events.publish(ActionFinished(result))
                    self.emit("action_completed", steps, {"action": action, "result": result})
                    if self.history is not None:
                        self.history.record(action.id, action.type, result.success, result.message)

                    target_info = self._extract_target_info(action, obs)
                    self._trajectory.append({
                        "step": steps,
                        "action": action.type,
                        "params": action.params,
                        "target": target_info.get("target"),
                        "bbox": target_info.get("bbox"),
                        "reason": target_info.get("reason"),
                        "obs_id": robs.obs_id,
                        "active_window": robs.context,
                        "result_success": result.success,
                        "result_msg": (result.message or "")[:200],
                    })

                    # --- Post-action focus drift check (via Recovery) ---
                    if action.type not in ("success", "fail", "focus_window") and target_app:
                        try:
                            post_obs = self.perception.observe()
                            post_robs = RuntimeObservation.from_obs(post_obs, belief.target_context)
                            if not post_robs.context_matches:
                                logger.warning("v2 post-action context violated: %r -> %r", target_app, post_robs.context)
                                self._trajectory[-1]["context_violated"] = True
                                self._trajectory[-1]["post_active"] = post_robs.context
                                recovery.focus_target(target_app, self._make_ctx(post_obs))
                                time.sleep(0.5)
                                obs = self.perception.observe()
                                self.events.publish(ObservationCreated(obs))
                                self._trajectory[-1]["recovery_active"] = getattr(obs, "active_window", "")
                                robs = RuntimeObservation.from_obs(obs, belief.target_context)
                                belief.update(robs)
                        except Exception:
                            pass

                    # --- Scroll Progress (via ProgressEvaluator) ---
                    if action.type == "scroll":
                        try:
                            post_obs = self.perception.observe()
                            post_robs = RuntimeObservation.from_obs(post_obs, belief.target_context)
                            verdict = progress.evaluate("scroll", robs, post_robs)
                            self.emit("progress", steps, {"progress": verdict})
                            progressed = verdict == "progress"
                            belief.register_scroll(direction, progressed)
                            target_visible_now = post_robs.target_visible
                            self._trajectory[-1]["scroll_progress"] = {
                                "prev_count": len(robs.candidates),
                                "new_count": len(post_robs.candidates),
                                "changed": progressed,
                                "target_visible": target_visible_now,
                            }
                            if not progressed:
                                self.emit("recovery_started", steps, {
                                    "recovery": {"reason": "scroll_no_progress",
                                                 "strategy": "policy_hint",
                                                 "previous_action": "scroll"},
                                })
                                recovery.apply_recovery("scroll_no_progress", belief, post_robs, self._make_ctx(obs))
                                hints += recovery.policy_for("scroll_no_progress", belief, post_robs)
                                self.emit("recovery_completed", steps, {
                                    "recovery": {"reason": "scroll_no_progress", "success": True},
                                })
                        except Exception:
                            pass

                    self.safety.record_step()
                    steps += 1
                    if not result.success:
                        self._batch_failed = result.message or "action failed"
                        break
                    if action.type == "success":
                        blocker = self._unconfirmed_edit()
                        if blocker:
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
                    expected = None
                    pending = None
                    if action.type == "click":
                        pending = self._capture_expected(obs, action)
                        expected = pending[1] if pending else None
                    light_observe = getattr(self.perception, "observe_light", None)
                    has_successor = (i + 1 < len(plan.actions)) and (batch_executed < config_batch_limit)
                    if not has_successor or light_observe is None:
                        if getattr(self.config, "enable_verification", True) and action.type == "click" and pending is not None:
                            self._pending_verify = pending
                        break
                    if getattr(self.config, "enable_verification", True):
                        light = light_observe()
                        ok, detail = verify_action(light_base, light, action, expected)
                        self.emit("verification", steps, {
                            "verification": {
                                "expected_state": expected,
                                "observed_state": detail,
                                "success": ok,
                                "evidence": {"action": action.type},
                            }
                        })
                        if not ok:
                            if self.history is not None:
                                self.history.record(action.id, action.type, False, f"verify: {detail}")
                            self._batch_failed = detail
                            break
                        light_base = light
                if finished_status in ("SUCCESS", "FAIL"):
                    break
                prev = obs
        except Exception as e:
            finished_status = "FAIL"
            finished_summary = f"loop error: {e}"
            self.emit("error", steps, {"error": str(e), "traceback": True})
        finally:
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
        self.emit("task_completed" if status == "SUCCESS" else "task_failed", steps,
                  {"status": status, "summary": finished_summary})
        if self._trajectory and self.state_dir:
            import json as _json
            os.makedirs(self.state_dir, exist_ok=True)
            traj_path = os.path.join(self.state_dir, f"trajectory_{self._task_id}.json")
            with open(traj_path, "w", encoding="utf-8") as f:
                _json.dump(self._trajectory, f, ensure_ascii=False, indent=2)
            logger.info("trajectory saved: %s (%d entries)", traj_path, len(self._trajectory))
        return result

    @staticmethod
    def _clicking_non_matching(action, robs: RuntimeObservation, keyword: str) -> bool:
        if not keyword:
            return False
        node_id = action.params.get("element_id")
        if node_id is None:
            return False
        clicked_text = ""
        scene = getattr(robs.raw, "scene", None)
        for n in getattr(scene, "nodes", []) or []:
            if n.id == int(node_id):
                clicked_text = (getattr(n, "text", "") or "").lower()
                break
        for e in getattr(robs.raw, "elements", []) or []:
            if e.id == int(node_id):
                clicked_text = (getattr(e, "text", "") or "").lower()
                break
        if not clicked_text:
            return False
        return keyword.lower() not in clicked_text

    @staticmethod
    def _pick_scroll_direction(action, belief: BeliefState) -> str:
        if belief.scroll_stall >= 1:
            return belief.next_scroll_direction()
        return action.params.get("direction") or "down"
