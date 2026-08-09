import logging
import os
import time
import uuid

from mio_cua.agent.diff import compute_diff
from mio_cua.automation.input_controller import InputController
from mio_cua.events import ObservationCreated, ActionStarted, ActionFinished, TaskFinished
from mio_cua.models.action_result import ActionResult
from mio_cua.models.task import Task, TaskResult
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
                 artifact_store=None, state_dir=None):
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
        self._task = None
        self._artifact_paths = []
        self._task_id = uuid.uuid4().hex[:8]
        self.scene_memory = SceneMemory()

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
            while not self.safety.should_stop():
                obs = self.perception.observe()
                self.events.publish(ObservationCreated(obs))
                self._save_state(obs, steps)
                self.scene_memory.push(getattr(obs, "scene", None))
                diff = compute_diff(prev, obs)
                if prev is not None and not diff.changes:
                    no_change += 1
                else:
                    no_change = 0
                hints = []
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
                if len(self._recent_sigs) >= 4 and self._recent_sigs.count(self._recent_sigs[-1]) >= 4:
                    hints.append(f"you have called `{self._recent_sigs[-1]}` repeatedly with no effect. STOP repeating it and choose a different action now.")
                if hints:
                    logger.debug("hints@%d: %s", steps, " | ".join(hints))
                plan = self.planner.plan(task, obs, diff, self.registry.schemas(), history=self.history, hints=hints)
                if not plan.actions:
                    break
                ctx = self._make_ctx(obs)
                for i, action in enumerate(plan.actions):
                    if self.safety.should_stop():
                        break
                    self.events.publish(ActionStarted(action))
                    ctx.current_action_id = action.id
                    try:
                        result = self.registry.call(action.type, action.params, ctx)
                    except Exception as e:
                        result = ActionResult(action.id, success=False, message=str(e), retryable=True)
                    if not result.success and result.retryable and self.recover is not None:
                        result = self.recover(action, result, ctx)
                    if result.success and action.type == "click":
                        self._pending_verify = self._capture_expected(obs, action)
                    self._save_artifact(obs, action, result)
                    self.events.publish(ActionFinished(result))
                    if self.history is not None:
                        self.history.record(action.id, action.type, result.success, result.message)
                    self.safety.record_step()
                    steps += 1
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
                    # Only ONE action per observation: the screen changes after
                    # every action, so subsequent actions in the same plan were
                    # decided against a stale scene. Re-observe + replan first.
                    # (Terminal success/fail already broke above.)
                    if i + 1 < len(plan.actions):
                        break
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
        """Check whether the previous click produced its expected change."""
        node_id, expected, prev_scene = self._pending_verify
        curr_scene = getattr(obs, "scene", None)
        if curr_scene is None:
            return None
        ok, detail = self._verifier.verify(prev_scene, curr_scene, expected)
        if ok:
            return None
        return (f"VERIFICATION: your last click on node {node_id} did not have the "
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
