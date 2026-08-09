from mio_cua.events import EventBus, ObservationCreated, TaskFinished
from mio_cua.models.observation import Observation


def test_subscribe_and_publish():
    bus = EventBus()
    seen = []
    bus.subscribe(ObservationCreated, lambda e: seen.append(e))
    obs = Observation(None, 1.0, None, 1.0, [])
    bus.publish(ObservationCreated(obs))
    assert len(seen) == 1
    assert seen[0].observation is obs


def test_unrelated_events_not_delivered():
    bus = EventBus()
    seen = []
    bus.subscribe(ObservationCreated, lambda e: seen.append(e))
    bus.publish(TaskFinished(__import__("mio_cua.models.task", fromlist=["TaskResult"]).TaskResult("SUCCESS")))
    assert seen == []
