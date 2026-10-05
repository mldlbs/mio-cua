from mio_cua.agent.verify import Verifier
from mio_cua.agent.recover import Recover
from mio_cua.models.action import Action
from mio_cua.models.action_result import RawResult, ActionResult


class FakePerception:
    def __init__(self, elements):
        self.elements = elements

    def observe(self):
        from mio_cua.models.observation import Observation
        return Observation(None, 1.0, None, 1.0, self.elements)


class FakeDispatch:
    def __init__(self):
        self.calls = []

    def __call__(self, name, params, ctx=None):
        self.calls.append((name, params))
        if name == "focus_window":
            return ActionResult(action_id="a-1", success=True, message="focused")
        return ActionResult(action_id="a-1", success=True, message="retried ok")


def test_verify_failed_input_is_not_success():
    v = Verifier(FakePerception([]))
    result = v.verify("a-1", RawResult(sent=False, error="boom"))
    assert result.success is False
    assert result.retryable is True


def test_verify_success_with_change():
    from mio_cua.models.element import Element
    v = Verifier(FakePerception([Element(0, "ocr", text="A")]))
    result = v.verify("a-1", RawResult(sent=True))
    assert result.success is True


def test_recover_focus_window_retry():
    d = FakeDispatch()
    r = Recover(dispatch=d, perception=FakePerception([]))
    action = Action(id="a-1", type="click", params={"x": 5, "y": 5})
    out = r.recover(action, ActionResult("a-1", False, retryable=True))
    assert out.success is True
    assert out.message == "retried ok"
    assert out.metadata.get("recovered") is True
    assert d.calls == [("focus_window", {"title": ""}), ("click", {"x": 5, "y": 5})]


def test_recover_retries_even_if_focus_fails():
    class FocusFailsDispatch:
        def __call__(self, name, params, ctx=None):
            return ActionResult(action_id="a-1", success=False, message="not found", retryable=True)

    d = FocusFailsDispatch()
    r = Recover(dispatch=d, perception=FakePerception([]), wait_s=0)
    result = ActionResult("a-1", False, retryable=True)
    out = r.recover(Action(id="a-1", type="click", params={"x": 1}), result)
    assert out.success is False
    assert out.metadata.get("recovered") is True


def test_recover_covers_key_and_scroll():
    d = FakeDispatch()
    r = Recover(dispatch=d, perception=FakePerception([]))
    for t in ("key", "scroll"):
        d.calls.clear()
        out = r.recover(Action(id="a-1", type=t, params={"keys": "enter"}),
                        ActionResult("a-1", False, retryable=True))
        assert out.success is True
        assert d.calls[0][0] == "focus_window"
        assert d.calls[1][0] == t


def test_recover_enforces_retry_cap():
    class FailingDispatch:
        def __call__(self, name, params, ctx=None):
            return ActionResult("a-1", False, message="still failing", retryable=True)

    r = Recover(dispatch=FailingDispatch(), perception=FakePerception([]),
                max_retries=2, wait_s=0)
    action = Action(id="a-1", type="click", params={"x": 1})
    first = r.recover(action, ActionResult("a-1", False, retryable=True))
    assert first.metadata.get("attempt") == 1
    second = r.recover(action, ActionResult("a-1", False, retryable=True))
    assert second.metadata.get("attempt") == 2
    third = r.recover(action, ActionResult("a-1", False, retryable=True))
    # cap reached: original result returned unchanged
    assert third.success is False
    assert third.metadata.get("recovered") is not True


def test_recover_skips_non_recoverable_types():
    d = FakeDispatch()
    r = Recover(dispatch=d, perception=FakePerception([]))
    result = ActionResult("a-1", False, retryable=True)
    out = r.recover(Action(id="a-1", type="screenshot", params={}), result)
    assert out is result
    assert d.calls == []
