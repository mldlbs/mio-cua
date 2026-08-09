from typing import Callable, Dict, Tuple

from mio_cua.tools.context import ToolContext


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tuple[Callable, dict]] = {}

    def register(self, name: str, func: Callable, schema: dict):
        self._tools[name] = (func, schema)

    def call(self, name: str, params: dict, ctx: ToolContext):
        func, _ = self._tools[name]
        return func(ctx, **params)

    def schemas(self) -> list:
        return [schema for _, schema in self._tools.values()]

    def names(self) -> list:
        return list(self._tools.keys())
