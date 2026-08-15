"""Batch execution support: in-batch per-step screen verification.

A plan may contain up to ``batch_limit`` actions. The loop executes them
consecutively, but re-observes the screen (light: OCR only) after each one to
confirm the action actually changed the screen before running the next. This
preserves "one action, one perception" safety while amortizing LLM calls across
a batch.
"""

from mio_cua.agent.expected import ExpectedVerifier
from mio_cua.scene.diff import diff as scene_diff
from mio_cua.scene.graph import SceneGraph

# Action types whose purpose is to change the on-screen content. For these we
# require an observable screen change when no explicit ``expected`` is present.
VISIBLE_TYPES = ("click", "type", "key", "scroll")


def verify_action(prev_obs, curr_obs, action, expected):
    """Verify an action's on-screen effect between two observations.

    Returns ``(ok, detail)``. Decision order:

    1. ``expected`` (from an affordance, e.g. ``{'display': True}``) is
       verified with ``ExpectedVerifier`` -- this is the strongest signal.
    2. else, if ``action.type`` is a visible action, fall back to a diff of the
       OCR-only layer between the two frames (any change = pass).
    3. else (wait/launch/move_mouse/fs tools/...) -> pass, the action is not
       expected to change the screen.
    """
    if expected:
        prev_scene = getattr(prev_obs, "scene", None)
        curr_scene = getattr(curr_obs, "scene", None)
        if prev_scene is not None and curr_scene is not None:
            return ExpectedVerifier().verify(prev_scene, curr_scene, expected)
    if action.type not in VISIBLE_TYPES:
        return True, "no visible expectation"
    changes = _ocr_diff(prev_obs, curr_obs)
    if changes:
        return True, "screen changed: " + "; ".join(changes[:3])
    return False, "screen did not change after action"


def _ocr_diff(prev_obs, curr_obs):
    """Diff ONLY the OCR layer of two observations.

    Light observations carry OCR-only scenes. Comparing them against a full
    scene directly would misreport every UIA/OmniParser node as "removed", so
    both frames are projected to their OCR nodes before the scene diff runs.
    """
    prev_nodes = _ocr_nodes(prev_obs)
    curr_nodes = _ocr_nodes(curr_obs)
    if not prev_nodes and not curr_nodes:
        return []
    prev = SceneGraph(nodes=prev_nodes)
    curr = SceneGraph(nodes=curr_nodes)
    return [c.description for c in scene_diff(prev, curr)]


def _ocr_nodes(obs):
    scene = getattr(obs, "scene", None)
    if scene is None:
        return []
    return [n for n in scene.nodes if (n.source or "") == "ocr"]
