"""Trace entry pairing: a step's thought must come from its own observation.

The step counter advances on every registry.call(), including the context
check's deterministic focus_window retries, which emit no plan. Pairing plans
with actions by ordinal (planner_records[i] <-> actions[i]) therefore shifted
every plan forward by the number of retries, so `entry.planner` described a
DIFFERENT step than `entry.obs_before` and the failure classifier judged
actions against thoughts from elsewhere in the trajectory.
"""

import sys
import os

sys.path.insert(0, r"E:\work\code\agent-dev\desktop-agent")

from mio_cua.evaluation.recorder import ActionRecord, PlannerRecord
from mio_cua.evaluation.trace import build_trace_entries


class _Obs:
    def __init__(self, window, proc="msedge"):
        self.active_window = window
        self.active_process = proc
        self.scene = None


def _capture(obs, metadata):
    return obs


def _prompt(window):
    return (
        "Task: open a browser and search\n"
        '{"context_state": {"active_app": "%s", "context_verified": true}}' % window
    )


def _scenario():
    """Reproduce trace_1790812617: 6 actions, only 4 of them planned.

    actions[0..1] are context-check focus_window retries (no plan), so the
    plans live at step indices 2..5.
    """
    actions = [
        ActionRecord(id="a0", type="focus_window", params={"title": "Edge"}),
        ActionRecord(id="a1", type="focus_window", params={"title": "Edge"}),
        ActionRecord(id="a2", type="key", params={"keys": "ctrl+t"}),
        ActionRecord(id="a3", type="type", params={"text": "今日新闻"}),
        ActionRecord(id="a4", type="click", params={"element_id": 104}),
        ActionRecord(id="a5", type="success", params={}),
    ]
    hub = _Obs("MIO·HUB — 任务总线")
    tab = _Obs("新建标签页 - 个人 - Microsoft Edge")
    results = _Obs("今日新闻 - 搜索 - 个人 - Microsoft Edge")

    raw = {0: _Obs("OpenCode", "opencode"), 2: hub, 3: tab, 4: tab, 5: results}
    eff = {2: hub, 3: tab, 4: tab, 5: results}
    plans = {
        2: PlannerRecord(prompt=_prompt("MIO·HUB — 任务总线")),
        3: PlannerRecord(prompt=_prompt("新建标签页 - 个人 - Microsoft Edge")),
        4: PlannerRecord(prompt=_prompt("新建标签页 - 个人 - Microsoft Edge")),
        5: PlannerRecord(prompt=_prompt("今日新闻 - 搜索 - 个人 - Microsoft Edge")),
    }
    return actions, eff, raw, plans


def test_planner_is_paired_with_its_own_observation():
    actions, eff, raw, plans = _scenario()
    entries = build_trace_entries(actions, eff, raw, plans, _capture)

    assert len(entries) == len(actions) == 6
    for i, entry in enumerate(entries):
        if entry.planner is None:
            continue
        # The whole point: the prompt's active_app must be THIS step's window.
        assert '"active_app": "%s"' % entry.obs_before.active_window in entry.planner.prompt, (
            f"step {i}: planner saw {entry.planner.prompt[-120:]!r} "
            f"but obs_before is {entry.obs_before.active_window!r}"
        )


def test_context_check_focus_steps_carry_no_plan():
    actions, eff, raw, plans = _scenario()
    entries = build_trace_entries(actions, eff, raw, plans, _capture)
    # Deterministic retries are not planner decisions; attaching a thought to
    # them invents a rationale the model never produced.
    assert entries[0].planner is None
    assert entries[1].planner is None
    assert entries[0].action.type == "focus_window"


def test_success_step_reads_the_results_window_not_the_previous_one():
    """The exact drift that made a finished run look like a hallucination."""
    actions, eff, raw, plans = _scenario()
    entries = build_trace_entries(actions, eff, raw, plans, _capture)

    last = entries[-1]
    assert last.action.type == "success"
    assert last.obs_before.active_window.startswith("今日新闻")
    assert "今日新闻" in last.planner.prompt


def test_ordinal_pairing_would_have_attached_the_wrong_plan():
    """Document the drift the step-keyed lookup removes.

    Appending plans in order and indexing actions by ordinal gives entry 0 the
    first plan -- whose prompt describes the MIO·HUB window -- while step 0
    actually observed OpenCode. Keying by step index leaves that entry with no
    plan instead of a fabricated one.
    """
    actions, eff, raw, plans = _scenario()
    entries = build_trace_entries(actions, eff, raw, plans, _capture)

    first_plan = list(plans.values())[0]
    assert "MIO·HUB" in first_plan.prompt          # what ordinal pairing would attach
    assert entries[0].obs_before.active_window == "OpenCode"   # what step 0 really saw
    assert entries[0].planner is None              # correct: no plan belongs here
    # Plans beyond the action count would have been dropped entirely.
    assert len(plans) < len(actions)
    assert entries[-1].planner is plans[5]
