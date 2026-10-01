import json

from mio_cua.automation.windows import (
    enumerate_taskbar,
    find_taskbar_element,
    locate_taskbar_hwnd,
)
from mio_cua.models.action import Action
from mio_cua.models.action_result import ActionResult

_ACTIONS = ("list", "click")


def taskbar(ctx, action="list", target=None):
    if action not in _ACTIONS:
        return ActionResult(
            ctx.current_action_id,
            False,
            f"unknown action: {action!r} (expected one of {list(_ACTIONS)})",
            retryable=False,
        )

    if action == "click" and not str(target or "").strip():
        return ActionResult(
            ctx.current_action_id,
            False,
            "target required for action='click'",
            retryable=False,
        )

    hwnd = locate_taskbar_hwnd()
    if not hwnd:
        return ActionResult(ctx.current_action_id, False, "taskbar not found", retryable=True)

    try:
        items, truncated = enumerate_taskbar(hwnd)
    except Exception as e:
        return ActionResult(ctx.current_action_id, False, f"enumerate failed: {e}", retryable=True)

    if action == "list":
        payload = {
            "action": "list",
            "count": len(items),
            "items": items,
            "truncated": truncated,
        }
        return ActionResult(
            ctx.current_action_id,
            True,
            json.dumps(payload, ensure_ascii=False),
            retryable=False,
        )

    element, matched_name, candidates = find_taskbar_element(hwnd, target)
    if element is None:
        return ActionResult(
            ctx.current_action_id,
            False,
            f"no taskbar item matches: {target!r}",
            retryable=True,
        )

    invoke_error = None
    try:
        element.invoke()
    except Exception as e:
        invoke_error = e

    if invoke_error is None:
        return ActionResult(
            ctx.current_action_id,
            True,
            f"clicked via invoke: {matched_name} (candidates={candidates})",
            retryable=False,
        )

    try:
        r = element.rectangle()
        cx = (int(r.left) + int(r.right)) // 2
        cy = (int(r.top) + int(r.bottom)) // 2
    except Exception as e:
        return ActionResult(
            ctx.current_action_id,
            False,
            f"invoke failed: {e}; rectangle unavailable for coordinate fallback",
            retryable=True,
        )

    try:
        result = ctx.controller.execute(
            Action(
                id=ctx.current_action_id,
                type="click",
                params={"x": cx, "y": cy, "button": "left", "double": False},
            )
        )
    except Exception as e:
        return ActionResult(
            ctx.current_action_id,
            False,
            f"invoke failed: {invoke_error}; coordinate fallback errored: {e}",
            retryable=True,
        )

    if not getattr(result, "sent", False):
        return ActionResult(
            ctx.current_action_id,
            False,
            f"invoke failed: {invoke_error}; coordinate fallback failed: {result.error}",
            retryable=True,
        )

    return ActionResult(
        ctx.current_action_id,
        True,
        f"clicked via coordinate ({cx},{cy}): {matched_name} (candidates={candidates})",
        retryable=False,
    )
