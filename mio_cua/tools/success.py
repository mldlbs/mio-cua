from mio_cua.models.action_result import ActionResult


def success(ctx, result):
    ctx.finished_status = "SUCCESS"
    ctx.finished_summary = str(result)
    return ActionResult(ctx.current_action_id, True, "task success")
