from typing import Callable, Dict, Tuple

from mio_cua.models.action_result import ActionResult
from mio_cua.safety.confirm import Confirmation
from mio_cua.tools.context import ToolContext


class ToolRegistry:
    def __init__(self, confirmation: Confirmation = None):
        self._confirmation = confirmation or Confirmation()
        self._tools: Dict[str, Tuple[Callable, dict]] = {}

    def register(self, name: str, func: Callable, schema: dict):
        self._tools[name] = (func, schema)

    def call(self, name: str, params: dict, ctx: ToolContext):
        if self._needs_confirmation(name):
            if not self._confirmation.confirm(name, params):
                return ActionResult(
                    ctx.current_action_id, False,
                    f"user rejected {name}: {params}", retryable=False,
                )
        func, _ = self._tools[name]
        return func(ctx, **params)

    def _needs_confirmation(self, name: str) -> bool:
        # Name-based fallback: even if a schema forgets the risk:"high" marker,
        # a tool whose name is in the HIGH_RISK list still gets confirmed.
        from mio_cua.safety.risk import is_high_risk
        if is_high_risk(name):
            return True
        _, schema = self._tools.get(name, (None, None))
        fn = (schema or {}).get("function", {})
        return fn.get("risk") == "high"

    def schemas(self) -> list:
        return [schema for _, schema in self._tools.values()]

    def names(self) -> list:
        return list(self._tools.keys())
