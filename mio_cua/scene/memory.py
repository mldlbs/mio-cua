"""Scene Memory: cross-frame state for the agent.

The core problem behind multi-step failures (e.g. crossapp): each observation
is isolated. The agent re-reads the same file, re-launches the same app,
because it has no record of *what it already saw and did*.

SceneMemory keeps the last N SceneGraphs and derives compact, task-relevant
facts the planner can inject into the next prompt:

- ``seen_texts``: text that appeared in recent frames (numbers read from a
  file, labels seen) -- the agent should not re-discover them.
- ``display_value``: the latest display readout (calculator result), updated
  across frames.
- ``recent_actions``: what was already attempted (from the loop's action
  history) so the planner can avoid repeating.
"""

import time

from mio_cua.scene.diff import display_text


class SceneMemory:
    def __init__(self, max_frames: int = 6):
        self.max_frames = max_frames
        self.frames = []  # list of SceneGraph
        self.seen_texts = set()
        self._display_value = ""

    def push(self, scene) -> None:
        if scene is None:
            return
        self.frames.append(scene)
        if len(self.frames) > self.max_frames:
            self.frames.pop(0)
        # collect stable texts from nodes
        for n in getattr(scene, "nodes", []) or []:
            t = (n.semantic or n.text or "").strip()
            if t:
                self.seen_texts.add(t)
        if len(self.seen_texts) > 200:
            self.seen_texts = set(sorted(self.seen_texts)[-200:])
        # latest display value
        dv = display_text(scene)
        if dv:
            self._display_value = dv

    @property
    def display_value(self) -> str:
        return self._display_value

    def summarize(self, recent_actions=None, max_texts: int = 40) -> str:
        """Compact memory summary for the planner's prompt."""
        parts = []
        if self._display_value:
            parts.append(f"display shows: {self._display_value!r}")
        texts = [t for t in self.seen_texts if self._is_useful(t)]
        if texts:
            parts.append("seen data/text: " + ", ".join(texts[:max_texts]))
        if recent_actions:
            parts.append("already done: " + "; ".join(recent_actions[-6:]))
        return "\n".join(parts)

    @staticmethod
    def _is_useful(t: str) -> bool:
        # ignore single punctuation and very short noise
        return len(t) >= 2 and any(ch.isalnum() for ch in t)
