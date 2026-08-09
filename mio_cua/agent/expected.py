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

    def verify(self, prev_scene, curr_scene, expected: dict) -> Tuple[bool, str]:
        """Return (ok, detail).

        ``ok`` is True when the display change matches ``expected`` (or there
        is nothing to verify). ``detail`` is a human-readable reason.
        """
        if not expected:
            return True, "no expectation"
        if "display" not in expected:
            return True, "no display expectation"
        return self._verify_display(prev_scene, curr_scene, expected["display"])

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
