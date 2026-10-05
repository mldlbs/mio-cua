__version__ = "0.1.0"

from mio_cua.config import AgentConfig
from mio_cua.models.task import Task


def __getattr__(name):
    if name == "Agent":
        from mio_cua.agent_factory import Agent
        return Agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["Agent", "AgentConfig", "Task", "__version__"]
