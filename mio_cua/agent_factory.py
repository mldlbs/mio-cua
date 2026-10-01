from mio_cua.agent.loop import AgentLoop
from mio_cua.agent.planner import Planner
from mio_cua.agent.recover import Recover
from mio_cua.agent.safety import Safety
from mio_cua.automation.grounding import Grounder
from mio_cua.automation.input_controller import InputController
from mio_cua.config import AgentConfig
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

    def run(self, task: Task, event_sinks=None, record: bool = False) -> TaskResult:
        """Run a task against the live desktop.

        MVP limitations:
        - `config.provider` is currently ignored; only the OpenAI-compatible
          provider is constructed.
        - Retryable failures are handled by the attached Recover strategy.

        Phase 3 recording:
        - When ``record=True`` the run is forced onto the v2 runtime (which
          carries the Phase 3 event bus) and a ``Recorder`` is attached as an
          event sink. The produced ``schema.Trace`` is auto-saved to
          ``<artifact_dir>/traces`` and exposed via ``self.last_recorder`` /
          ``self.last_trace_dir`` for downstream replay / attribution / benchmark.
        """
        self.last_recorder = None
        self.last_trace_dir = None

        sinks = list(event_sinks or [])
        if record:
            from mio_cua.evaluation.recorder import Recorder, JSONLTraceStore

            trace_dir = os.path.join(self.config.artifact_dir, "traces")
            recorder = Recorder(store=JSONLTraceStore(trace_dir), auto_save=True)
            sinks.append(recorder)
            self.last_recorder = recorder
            # Phase 3 recording requires the v2 event bus.
            if not getattr(self.config, "runtime_v2", False):
                self.config = AgentConfig(**{**self.config.data, "runtime_v2": True})

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
        if getattr(self.config, "runtime_v2", False):
            from mio_cua.runtime.loop import AgentLoopV2

            loop_cls = AgentLoopV2
        else:
            loop_cls = AgentLoop
        loop = loop_cls(
            perception=self._perception(),
            planner=planner,
            registry=self.registry,
            safety=safety,
            events=self.events,
            config=self.config,
            history=History(),
            controller=InputController(
                # Mount the deterministic Grounder by default (fail-soft: it
                # degrades to the cached bbox whenever the live desktop is
                # unreadable, and only refuses to click when the target is
                # genuinely missing/occluded/ambiguous). This is the execution
                # boundary half of "de-modeling" and was previously dormant
                # unless runtime_v2 was on.
                grounder=Grounder() if getattr(self.config, "enable_grounding", True) else None
            ),
            artifact_store=ArtifactStore(self.config.artifact_dir),
            state_dir=os.path.join(self.config.artifact_dir, "state"),
            recover=Recover(self._dispatch, self._perception()),
            event_sinks=sinks,
        )
        result = loop.run(task)
        if self.last_recorder is not None and self.last_recorder.trace is not None:
            self.last_trace_dir = self.last_recorder.save()
        return result

    def _dispatch(self, name, params, ctx=None):
        from mio_cua.models.action_result import ActionResult
        if ctx is None:
            return ActionResult("", success=False, message="no tool context", retryable=True)
        return self.registry.call(name, params, ctx)

    def _perception(self):
        from mio_cua.perception import Perception
        return Perception(screenshot_dir=self.config.artifact_dir)
