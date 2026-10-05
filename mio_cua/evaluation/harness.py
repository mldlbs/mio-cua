"""Benchmark harness: run a TaskDataset against the live AgentLoop and capture
trajectories + observational signals (no loop behavior change)."""

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from mio_cua.evaluation.dataset import BenchmarkTask

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    task_id: str
    status: str
    steps: int
    duration: float
    trajectory: List[Dict[str, Any]] = field(default_factory=list)
    context_violations: int = 0
    target_violations: int = 0
    scroll_stalls: int = 0
    recoveries: int = 0
    artifacts: int = 0
    summary: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "steps": self.steps,
            "duration": round(self.duration, 2),
            "context_violations": self.context_violations,
            "target_violations": self.target_violations,
            "scroll_stalls": self.scroll_stalls,
            "recoveries": self.recoveries,
            "artifacts": self.artifacts,
            "summary": self.summary[:500],
            "error": self.error[:500],
        }


class Harness:
    """Runs benchmark tasks and captures observational signals.

    Instrumentation is applied once at construction by monkeypatching
    ``AgentLoop.run`` (trajectory capture) and wrapping
    ``AgentLoop._check_target_visibility`` (target-violation counting).
    """

    _patched = False

    def __init__(
        self,
        config,
        run_dir: str,
        api_key: Optional[str] = None,
        api_key_env: str = "MIO_API_KEY",
    ):
        self.config = config
        self.run_dir = run_dir
        self.api_key = api_key
        self.api_key_env = api_key_env
        os.makedirs(run_dir, exist_ok=True)
        self._trajectory: List[Dict[str, Any]] = []
        self._counters: Dict[str, int] = {}
        self._patch()

    def _patch(self) -> None:
        if Harness._patched:
            return
        from mio_cua.agent.loop import AgentLoop

        capture = self._trajectory
        counters = self._counters

        def make_patch(orig):
            def patched_run(self_loop, task):
                result = orig(self_loop, task)
                capture.extend(getattr(self_loop, "_trajectory", []))
                return result

            return patched_run

        AgentLoop.run = make_patch(AgentLoop.run)
        # v2 subclasses AgentLoop and overrides run(); patch it too so the
        # harness captures v2 trajectories.
        try:
            from mio_cua.runtime.loop import AgentLoopV2

            AgentLoopV2.run = make_patch(AgentLoopV2.run)
        except Exception:  # pragma: no cover - v2 optional
            pass

        orig_check = AgentLoop._check_target_visibility

        def wrapped_check(self_loop, action, obs, task):
            ok = orig_check(self_loop, action, obs, task)
            if not ok:
                counters["target_violations"] = counters.get("target_violations", 0) + 1
            return ok

        AgentLoop._check_target_visibility = wrapped_check
        Harness._patched = True

    def run_task(self, bt: BenchmarkTask) -> RunResult:
        self._trajectory.clear()
        self._counters.clear()
        if self.api_key:
            os.environ[self.api_key_env] = self.api_key

        task_artifact = os.path.join(self.run_dir, "artifacts", bt.id)
        os.makedirs(task_artifact, exist_ok=True)
        cfg = type(self.config)(**{**self.config.data, "artifact_dir": task_artifact})

        from mio_cua.agent_factory import Agent

        agent = Agent(cfg)
        t0 = time.time()
        status = "ERROR"
        summary = ""
        error = ""
        artifacts = 0
        raw_steps = 0
        try:
            result = agent.run(bt.to_task())
            status = result.status
            summary = result.summary or ""
            artifacts = len(getattr(result, "artifacts", []) or [])
            raw_steps = getattr(result, "steps", 0)
        except Exception as e:  # noqa: BLE001 - benchmark must record, not crash
            error = str(e)
        duration = time.time() - t0

        traj = list(self._trajectory)
        context_violations = sum(1 for e in traj if e.get("context_violated"))
        scroll_stalls = sum(
            1 for e in traj if (e.get("scroll_progress") or {}).get("changed") is False
        )
        recoveries = sum(1 for e in traj if e.get("recovery_active"))
        # target_violations may come from the wrapped fn (v1) or from the
        # trajectory flag recorded by v2's Belief-based blocking.
        traj_target_violations = sum(1 for e in traj if e.get("target_violated"))
        target_violations = self._counters.get("target_violations", 0) + traj_target_violations

        return RunResult(
            task_id=bt.id,
            status=status,
            steps=raw_steps or len(traj),
            duration=duration,
            trajectory=traj,
            context_violations=context_violations,
            target_violations=target_violations,
            scroll_stalls=scroll_stalls,
            recoveries=recoveries,
            artifacts=artifacts,
            summary=summary,
            error=error,
        )

    def run_all(self, tasks: List[BenchmarkTask]) -> List[RunResult]:
        results: List[RunResult] = []
        for bt in tasks:
            logger.info("benchmark task %s", bt.id)
            results.append(self.run_task(bt))
        return results
