from dataclasses import dataclass
from typing import Callable, Dict, List, Type


class Event:
    pass


@dataclass
class ObservationCreated(Event):
    observation: object


@dataclass
class ActionStarted(Event):
    action: object


@dataclass
class ActionFinished(Event):
    result: object


@dataclass
class TaskFinished(Event):
    result: object


class EventBus:
    def __init__(self):
        self._subscribers: Dict[Type[Event], List[Callable]] = {}

    def subscribe(self, event_type: Type[Event], handler: Callable):
        self._subscribers.setdefault(event_type, []).append(handler)

    def publish(self, event: Event):
        for handler in self._subscribers.get(type(event), []):
            handler(event)
