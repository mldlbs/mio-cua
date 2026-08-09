from mio_cua.agent.loop import AgentLoop
from mio_cua.agent.planner import Planner
from mio_cua.agent.recover import Recover
from mio_cua.agent.safety import Safety
from mio_cua.automation.input_controller import InputController
from mio_cua.events import EventBus
from mio_cua.memory.artifact import ArtifactStore
from mio_cua.memory.history import History
import os
from mio_cua.models.task import Task, TaskResult
from mio_cua.prompts import DEFAULT_SYSTEM_PROMPT
from mio_cua.providers.openai_compat import OpenAICompatProvider
from mio_cua.tools.builtin import register_builtin_tools
from mio_cua.tools.registry import ToolRegistry


class Agent:
    """Public SDK entry point for the desktop agent.

    Wires the provider, planner, safety, perception, and tools into an
    AgentLoop. Subscribers can attach to `agent.events` to observe the run.
    """

    def __init__(self, config):
        self.config = config
        self.events = EventBus()
        self.registry = ToolRegistry()
        register_builtin_tools(self.registry)

    def run(self, task: Task) -> TaskResult:
        """Run a task against the live desktop.

        MVP limitations:
        - `config.provider` is currently ignored; only the OpenAI-compatible
          provider is constructed.
        - Retryable failures are handled by the attached Recover strategy.
        """
        provider = OpenAICompatProvider(
            base_url=self.config.base_url,
            api_key=self.config.api_key(),
            model=self.config.model,
        )
        planner = Planner(provider, DEFAULT_SYSTEM_PROMPT)
        safety = Safety(
            max_steps=self.config.max_steps,
            timeout_s=self.config.task_timeout_s,
            emergency_key=self.config.emergency_key,
        )
        loop = AgentLoop(
            perception=self._perception(),
            planner=planner,
            registry=self.registry,
            safety=safety,
            events=self.events,
            config=self.config,
            history=History(),
            controller=InputController(),
            artifact_store=ArtifactStore(self.config.artifact_dir),
            state_dir=os.path.join(self.config.artifact_dir, "state"),
            recover=Recover(self._dispatch, self._perception()),
        )
        return loop.run(task)

    def _dispatch(self, name, params, ctx=None):
        from mio_cua.models.action_result import ActionResult
        if ctx is None:
            return ActionResult("", success=False, message="no tool context", retryable=True)
        return self.registry.call(name, params, ctx)

    def _perception(self):
        from mio_cua.perception import Perception
        return Perception(screenshot_dir=self.config.artifact_dir)
