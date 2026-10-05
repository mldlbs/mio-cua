from mio_cua import Agent, AgentConfig, Task
from mio_cua.config import AgentConfig as AC


def test_agent_config_alias():
    cfg = AgentConfig(max_steps=10)
    assert cfg.max_steps == 10


def test_agent_constructs():
    a = Agent(AgentConfig(provider="openai", model="gpt-4o"))
    assert a is not None
