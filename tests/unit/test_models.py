from mio_cua.models.element import Element
from mio_cua.models.observation import Observation, Change, ObservationDiff
from mio_cua.models.action import Action, Plan, ToolCall
from mio_cua.models.action_result import RawResult, ActionResult
from mio_cua.models.task import Task, TaskResult


def test_element_defaults():
    e = Element(id=3, source="ocr", bbox=(0, 0, 10, 10))
    assert e.id == 3
    assert e.role == "unknown"
    assert e.confidence == 1.0
    assert e.enabled is True


def test_observation_diff_holds_changes():
    prev = Observation(None, 1.0, None, 1.0, [])
    cur = Observation(None, 2.0, None, 1.0, [])
    d = ObservationDiff(prev=prev, current=cur, changes=[Change("added", 1, "new window")])
    assert d.changes[0].kind == "added"
    assert d.current is cur


def test_action_and_toolcall():
    a = Action(id="a-1", type="click", params={"element_id": 2})
    tc = ToolCall(id="t-1", name="click", arguments={"element_id": 2})
    assert tc.name == "click"
    assert a.type == "click"


def test_action_result_separation():
    raw = RawResult(sent=True)
    assert raw.sent is True
    result = ActionResult(action_id="a-1", success=True, observation_changed=True)
    assert result.retryable is False


def test_task_result_fields():
    r = TaskResult(status="SUCCESS", task_id="t1", steps=3)
    assert r.status == "SUCCESS"
    assert r.usage == {}
