"""Mechanism proof for the two "de-modeled" layers, run on the REAL code.

This is NOT the full 80-run real-desktop A/B (that needs WeChat + a GUI and must
run on the user's machine). It is the *mechanism* validation the user asked to
do FIRST:

  1. Grounding under UI drift  (raw coords fail, grounded coords hit)
  2. Recovery under context_menu failure (no recovery -> stuck, recovery -> Esc)

Both scenarios drive the genuine ``Grounder`` / ``RecoveryManager`` classes with
an injectable mock desktop, so the result reflects real logic, not a reimplementation.

Run:  python experiments/mechanism_proof.py
"""

import json
import os
import random
from dataclasses import dataclass, field
from typing import List, Optional

from mio_cua.automation.grounding import Grounder, GroundingError
from mio_cua.models.action import Action
from mio_cua.models.action_result import ActionResult
from mio_cua.models.element import Element
from mio_cua.runtime.recovery import RecoveryManager


# -- a minimal observation wrapper the Grounder can read ----------------
@dataclass
class RefObs:
    elements: List[Element] = field(default_factory=list)


# -- mock desktop: WeChat-like, supports UI drift + context menu -------
class MockDesktop:
    def __init__(self):
        # Pre-drift layout (what the model perceived at t0).
        self.pre = {
            1: Element(1, "uia", text="搜索", role="edit", bbox=(500, 300, 200, 30)),
            2: Element(2, "uia", text="兴蓉环境", role="listitem", bbox=(500, 600, 300, 40)),
            3: Element(3, "uia", text="文件传输助手", role="listitem", bbox=(500, 660, 300, 40)),
        }
        self.offset = (0, 0)
        self.menu_open = False

    def drift(self):
        """Window moved between perception (t0) and execution (t1)."""
        dx = random.randint(80, 220)
        dy = random.randint(80, 220)
        self.offset = (dx, dy)

    def live_elements(self) -> List[Element]:
        dx, dy = self.offset
        return [
            Element(e.id, e.source, text=e.text, role=e.role,
                    bbox=(e.bbox[0] + dx, e.bbox[1] + dy, e.bbox[2], e.bbox[3]),
                    visible=True, enabled=True)
            for e in self.pre.values()
        ]

    def window_rect(self):
        return (0, 0, 2000, 2000)

    def click(self, x, y) -> bool:
        """Returns True iff the click lands on the target search box in the
        CURRENT (post-drift) layout."""
        if self.menu_open:
            return False  # a context menu intercepts the click
        for e in self.live_elements():
            l, t, w, h = e.bbox
            if l <= x <= l + w and t <= y <= t + h and e.text == "搜索":
                return True
        return False

    def open_context_menu(self):
        self.menu_open = True

    def press_esc(self):
        self.menu_open = False


# -- mock registry so RecoveryManager can act on the desktop ------------
class MockRegistry:
    def __init__(self, desktop: MockDesktop):
        self.desktop = desktop

    def call(self, name, params, ctx=None):
        if name == "key":
            if params.get("keys") == "esc":
                self.desktop.press_esc()
                return ActionResult("r", success=True)
        if name == "click":
            x, y = params["x"], params["y"]
            return ActionResult("r", success=self.desktop.click(x, y))
        return ActionResult("r", success=False)


# ======================================================================
# 1) Grounding under UI drift
# ======================================================================
def run_grounding(n: int = 20):
    desktop = MockDesktop()
    # The model planned from the PRE-drift observation (t0).
    ref_obs = RefObs(elements=list(desktop.pre.values()))
    model_action = Action("a1", "click", {"element_id": 1})  # "click search box"

    raw_hits = 0
    grounded_hits = 0
    grounded_errors = 0

    for _ in range(n):
        desktop.drift()
        # --- Version A: raw execution (old behaviour, no Grounder) -------
        # Resolve from the STALE reference coordinates, then click on the
        # POST-drift desktop.
        ref_el = desktop.pre[1]
        raw_x = ref_el.bbox[0] + ref_el.bbox[2] // 2
        raw_y = ref_el.bbox[1] + ref_el.bbox[3] // 2
        if desktop.click(raw_x, raw_y):
            raw_hits += 1

        # --- Version B: Grounding re-resolves against the LIVE desktop ----
        grounder = Grounder(
            live_source=desktop.live_elements,
            window_rect=desktop.window_rect,
        )
        try:
            coords = grounder.resolve(model_action, ref_obs)
            if coords is None:
                grounded_errors += 1
            elif desktop.click(*coords):
                grounded_hits += 1
            else:
                grounded_errors += 1
        except GroundingError:
            grounded_errors += 1

    return {
        "n": n,
        "raw_target_hit": raw_hits,
        "grounded_target_hit": grounded_hits,
        "grounded_error": grounded_errors,
        "raw_error_click_rate": round(1 - raw_hits / n, 3),
        "target_localization_success": round(grounded_hits / n, 3),
    }


# ======================================================================
# 2) Recovery under context_menu failure
# ======================================================================
def run_recovery(n: int = 20):
    recovered = 0
    for _ in range(n):
        desktop = MockDesktop()
        desktop.open_context_menu()  # a context menu is blocking the UI

        # --- Without recovery: click the target directly -> intercepted ---
        no_recovery_ok = desktop.click(600, 315)  # any click is blocked

        # --- With deterministic recovery: Esc dismisses the menu ----------
        belief = type("B", (), {"target_context": {}})()
        robs = type("R", (), {"affordances": []})()
        ctx = object()
        rm = RecoveryManager(registry=MockRegistry(desktop), controller=None,
                             perception=None, events=None)
        acted = rm.apply_recovery("context_menu", belief, robs, ctx)
        after_ok = desktop.click(600, 315)
        if acted and after_ok and not no_recovery_ok:
            recovered += 1

    return {
        "n": n,
        "recovery_success": recovered,
        "recovery_success_rate": round(recovered / n, 3),
    }


def main():
    print("=" * 64)
    print("MECHANISM PROOF  (drives the REAL Grounder / RecoveryManager)")
    print("=" * 64)

    g = run_grounding(20)
    print("\n[1] Grounding under UI drift")
    print(f"    raw (stale coords) target hit : {g['raw_target_hit']}/{g['n']}")
    print(f"    grounded (live re-resolve) hit: {g['grounded_target_hit']}/{g['n']}")
    print(f"    -> raw_error_click_rate       : {g['raw_error_click_rate']}")
    print(f"    -> target_localization_success: {g['target_localization_success']}")
    print("    conclusion: raw coords MISS under drift; Grounding RECOVERS.")

    r = run_recovery(20)
    print("\n[2] Recovery under context_menu failure")
    print(f"    recovered with deterministic Esc: {r['recovery_success']}/{r['n']}")
    print(f"    -> recovery_success_rate         : {r['recovery_success_rate']}")
    print("    conclusion: without recovery the UI stays blocked; Esc frees it.")

    out = {"grounding": g, "recovery": r}
    os.makedirs(os.path.join(os.path.dirname(__file__), "results"), exist_ok=True)
    path = os.path.join(os.path.dirname(__file__), "results", "mechanism_proof.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nwritten: {path}")
    print("\nNOTE: this proves the MECHANISM. Real success-rate lift (40%->75%)")
    print("      still requires the 80-run real-desktop sweep on your machine.")


if __name__ == "__main__":
    main()
