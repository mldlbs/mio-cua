"""Programmatic action verification against an affordance's ``expected``.

The perception layer annotates click candidates with an ``expected`` dict
(e.g. ``{'display': True}`` for calculator digits, ``{'display': 'unchanged'}``
for operators). The LLM sees this hint but the loop never checks whether the
screen actually changed as expected. This module closes that gap: after an
action, diff the display nodes and report whether the expected change happened,
so the loop can tell the agent "that click registered" vs "it did not".

This reduces the classic failure where the agent clicks a key, the display did
not change, and it either repeats the click (thinking it missed) or moves on
(not noticing it missed).
"""

from typing import Optional, Tuple

from mio_cua.scene.diff import display_text


class ExpectedVerifier:
    """Verify an action's outcome against its expected screen change."""

    def verify(self, prev_scene, curr_scene, expected: dict,
                node_id=None, curr_active_window=None) -> Tuple[bool, str]:
        """Return (ok, detail).

        ``ok`` is True when the screen change matches ``expected`` (or there
        is nothing to verify). ``detail`` is a human-readable reason.

        ``node_id`` / ``curr_active_window`` let expectations that are not
        about the calculator display be checked: ``state_toggle`` (a checkbox
        flipped), ``window_title`` (the right window is now foreground), and
        ``text_contains`` (a field now holds/some text).
        """
        if not expected:
            return True, "no expectation"
        if "display" in expected:
            return self._verify_display(prev_scene, curr_scene, expected["display"])
        if "state_toggle" in expected:
            return self._verify_state_toggle(prev_scene, curr_scene, node_id)
        if "window_title" in expected:
            return self._verify_window_title(expected["window_title"], curr_active_window)
        if "text_contains" in expected:
            return self._verify_text_contains(prev_scene, curr_scene, node_id,
                                             expected["text_contains"])
        return True, "no display expectation"

    def _verify_display(self, prev_scene, curr_scene, want) -> Tuple[bool, str]:
        prev_text = display_text(prev_scene) if prev_scene is not None else ""
        curr_text = display_text(curr_scene) if curr_scene is not None else ""
        changed = bool(prev_text and prev_text != curr_text)

        if want is True:
            if changed:
                return True, f"display changed: {prev_text!r} -> {curr_text!r}"
            return False, f"display did not change (still {curr_text!r})"
        if want == "unchanged":
            if changed:
                return False, f"display changed unexpectedly: {prev_text!r} -> {curr_text!r}"
            return True, f"display unchanged ({curr_text!r})"
        return True, "unknown expectation"

    def _verify_state_toggle(self, prev_scene, curr_scene, node_id) -> Tuple[bool, str]:
        """A checkbox/radio/toggle should have flipped its ``checked`` state."""
        if node_id is None:
            return True, "no node to verify toggle"
        p = self._node(prev_scene, node_id)
        c = self._node(curr_scene, node_id)
        if p is None or c is None:
            return True, "toggle node absent in a frame (cannot verify)"
        if not (p.state or {}) or not (c.state or {}):
            return True, "no UIA state in observation (deferred to full obs)"
        pc = bool((p.state or {}).get("checked"))
        cc = bool((c.state or {}).get("checked"))
        if pc != cc:
            return True, f"toggle state flipped: {pc} -> {cc}"
        return False, f"toggle state did not change (still {cc})"

    def _verify_window_title(self, want, curr_active_window) -> Tuple[bool, str]:
        """The action should have brought ``want`` to the foreground."""
        if not want:
            return True, "no window title expectation"
        cur = (curr_active_window or "").lower()
        if want.lower() in cur:
            return True, f"active window matches {want!r}"
        return False, f"active window {curr_active_window!r} does not match {want!r}"

    def _verify_text_contains(self, prev_scene, curr_scene, node_id, want) -> Tuple[bool, str]:
        """A field should hold / have gained text after a ``type`` action."""
        if node_id is None:
            return True, "no node to verify text"
        c = self._node(curr_scene, node_id)
        if c is None:
            return True, "node absent (cannot verify)"
        ct = (c.semantic or c.text or "").strip()
        if want is True:
            if ct:
                return True, f"field now contains text: {ct!r}"
            return False, "field is still empty after type"
        if want and want.lower() in ct.lower():
            return True, f"field contains {want!r}"
        return False, f"field does not contain {want!r}"

    @staticmethod
    def _node(scene, node_id):
        if scene is None:
            return None
        return scene.node(node_id) if hasattr(scene, "node") else None
