from mio_cua.models.action_result import ActionResult, RawResult


class Verifier:
    """Converts a RawResult (input transport) into an ActionResult (business outcome).

    Note: ``observation_changed`` currently reflects only "the fresh observation
    contains elements", NOT a true screen diff. A proper change signal lives in
    ``agent.diff.compute_diff``; wiring it here is future work.
    """

    def __init__(self, perception):
        self.perception = perception

    def verify(self, action_id: str, raw: RawResult) -> ActionResult:
        if not raw.sent:
            return ActionResult(action_id, success=False, message=raw.error or "input failed", retryable=True)
        try:
            current = self.perception.observe()
            populated = len(current.elements) > 0
            return ActionResult(action_id, success=True, message="ok", observation_changed=populated)
        except Exception as e:
            return ActionResult(action_id, success=False, message=str(e), retryable=True)
