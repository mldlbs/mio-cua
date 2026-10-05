import os
import time

from mio_cua.vision.screen import capture
from mio_cua.models.action_result import ActionResult


def screenshot(ctx, region=None):
    try:
        img = capture()
        path = None
        if ctx.config is not None and getattr(ctx.config, "artifact_dir", None):
            os.makedirs(ctx.config.artifact_dir, exist_ok=True)
            path = os.path.join(ctx.config.artifact_dir, f"shot_{int(time.time() * 1000)}.png")
            img.save(path)
        return ActionResult(ctx.current_action_id, True, path or "captured", metadata={"path": path})
    except Exception as e:
        return ActionResult(ctx.current_action_id, False, str(e), retryable=True)
