"""V1 and V2 must produce the SAME stats fields from their own artefacts.

V1 has no event bus, so its numbers are derived from the trajectory plus the
log it already writes. These tests pin that both adapters agree on the action
counters for the same run, and that V1 fields it never measured stay 0 rather
than being invented.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.ab.events import (  # noqa: E402
    action_counts,
    stats_for,
    stats_from_events,
    stats_from_v1,
)


def _click(target, success=True, violated=False, reason="ok"):
    return {"step": 1, "action": "click", "target": target,
            "result_success": success, "target_violated": violated, "reason": reason}


# ── shared action counters ──

def test_action_counts_marks_blocked_separately_from_executed():
    traj = [
        _click("另一个群", success=False, reason="blocked: target invisible"),
        _click("目标群", success=True),
        {"step": 2, "action": "type", "target": None, "result_success": True},
        {"step": 3, "action": "success", "result_success": True},
    ]
    s = action_counts(traj, keyword="目标群")
    assert s.blocked == 1
    assert s.clicks == 1          # only the executed click
    assert s.misclicks == 0
    assert s.actions == 2         # click + type; success() is not an action


def test_action_counts_flags_a_wrong_target_click():
    s = action_counts([_click("另一个群", success=True)], keyword="目标群")
    assert s.misclicks == 1


# ── V2 ──

def test_v2_stats_from_events():
    events = [
        {"type": "plan_created", "payload": {}},
        {"type": "plan_created", "payload": {}},
        {"type": "verification", "payload": {"verification": {"success": True}}},
        {"type": "verification", "payload": {"verification": {"success": False}}},
        {"type": "recovery_started", "payload": {"recovery": {"reason": "obstruction"}}},
        {"type": "recovery_completed", "payload": {"recovery": {"success": True}}},
    ]
    s = stats_from_events(events)
    assert s.plans == 2
    assert s.verifications == 2 and s.verifications_failed == 1
    assert s.recoveries_started == 1 and s.recoveries_completed == 1
    assert s.recoveries_ok == 1


# ── V1 ──

def test_v1_stats_derived_without_touching_the_runtime():
    traj = [
        _click("另一个群", success=False, reason="blocked: target invisible"),
        {**_click("目标群"), "recovery": "context_menu:dismissed"},
    ]
    log = "obstruction: context menu detected, dismissing with Esc\n"
    s = stats_from_v1(traj, log, keyword="目标群")
    assert s.blocked == 1 and s.clicks == 1 and s.misclicks == 0
    assert s.recoveries_started >= 2          # obstruction + context_menu
    # V1 never reports completion; do not invent it
    assert s.recoveries_completed == 0 and s.recoveries_ok == 0
    assert s.extra["v1_recovery_reasons"]


def test_v1_log_lines_contribute_recovery_reasons():
    s = stats_from_v1([], "post-action context violated: expected='Edge' got='x'\n")
    assert "context_mismatch" in s.extra["v1_recovery_reasons"]


# ── the same run through both adapters ──

def test_both_adapters_agree_on_action_fields_for_the_same_run():
    traj = [_click("另一个群", success=False, reason="blocked: target invisible"),
            _click("目标群", success=True)]
    v2 = stats_for({"trajectory": traj, "keyword": "目标群", "events": []})
    v1 = stats_for({"trajectory": traj, "keyword": "目标群", "log_text": ""})
    for field in ("actions", "clicks", "blocked", "misclicks"):
        assert getattr(v2, field) == getattr(v1, field), field


def test_stats_for_dispatches_by_shape():
    assert stats_for({"events": []}).events_source == "events"
    assert stats_for({"trajectory": [], "log_text": ""}).events_source == "trajectory+log"
