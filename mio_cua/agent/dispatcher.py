from typing import Callable, List

from mio_cua.models.action import Plan
from mio_cua.models.action_result import ActionResult


class Dispatcher:
    """Executes a plan of actions through a tool registry.

    The `recover` callable must accept `(action, result, ctx)` and return an
    ActionResult. If None, a default recovery that re-dispatches the action
    through the registry (bound to ctx) is used.
    """

    def __init__(self, registry, recover: Callable = None):
        self.registry = registry
        self.recover = recover

    def _default_recover(self, action, result, ctx):
        return result

    def execute(self, plan: Plan, safety, ctx) -> List[ActionResult]:
        results = []
        for action in plan.actions:
            if safety.should_stop():
                break
            ctx.current_action_id = action.id
            try:
                result = self.registry.call(action.type, action.params, ctx)
            except Exception as e:
                result = ActionResult(action.id, success=False, message=str(e), retryable=True)
            if not result.success and result.retryable:
                if self.recover is not None:
                    result = self.recover(action, result, ctx)
                else:
                    result = self._default_recover(action, result, ctx)
            results.append(result)
            safety.record_step()
        return results
