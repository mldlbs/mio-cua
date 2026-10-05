"""Run a desktop task via the SDK."""
import os

from mio_cua import Agent, AgentConfig, Task
from mio_cua.events import ActionStarted

cfg = AgentConfig(
    provider=os.environ.get("mio_cua_PROVIDER", "openai"),
    model=os.environ.get("mio_cua_MODEL", "gpt-4o"),
    max_steps=30,
)

agent = Agent(cfg)
agent.events.subscribe(ActionStarted, lambda e: print(f"[action] {e.action.type}"))

# 交互工具(click/type/key)已接入真实输入控制器。请确认 F9 急停可用后再运行。
result = agent.run(Task(instruction="打开记事本程序，输入 hello world，等待 2 秒，然后截图"))
print(f"{result.status}: {result.summary} steps={result.steps}")
