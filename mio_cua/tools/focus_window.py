from mio_cua.automation.windows import focus_window as fw
from mio_cua.models.action_result import ActionResult


def focus_window(ctx, title):
    try:
        ok = fw(title)
    except Exception as e:
        return ActionResult(ctx.current_action_id, False, str(e), retryable=True)
    return ActionResult(ctx.current_action_id, ok, "focused" if ok else f"not found: {title}", retryable=not ok)
