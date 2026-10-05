import time

from mio_cua.models.action import Action
from mio_cua.models.action_result import ActionResult


class Recover:
    """Recovery strategies for retryable action failures.

    Brings the active window to the foreground (so clicks/typing land on the
    right target), then re-issues the action. Each action is retried at most
    ``max_retries`` times to avoid endless retry loops.
    """

    RECOVERABLE = ("click", "type", "key", "scroll", "move_mouse")

    def __init__(self, dispatch, perception, max_retries: int = 2, wait_s: float = 0.5):
        self.dispatch = dispatch
        self.perception = perception
        self.max_retries = max_retries
        self.wait_s = wait_s
        self._retries = {}

    def __call__(self, action: Action, result: ActionResult, ctx=None) -> ActionResult:
        return self.recover(action, result, ctx)

    def recover(self, action: Action, result: ActionResult, ctx=None) -> ActionResult:
        if action.type not in self.RECOVERABLE or not result.retryable:
            return result
        n = self._retries.get(action.id, 0)
        if n >= self.max_retries:
            return result
        self._retries[action.id] = n + 1

        try:
            title = self._active_title()
            focus = self.dispatch("focus_window", {"title": title}, ctx=ctx)
        except Exception:
            return result

        if not focus.success:
            time.sleep(self.wait_s)

        retry = self.dispatch(action.type, action.params, ctx=ctx)
        retry.metadata = dict(retry.metadata or {})
        retry.metadata["recovered"] = True
        retry.metadata["attempt"] = self._retries[action.id]
        return retry

    def _active_title(self) -> str:
        obs = self.perception.observe()
        return obs.active_window or ""
