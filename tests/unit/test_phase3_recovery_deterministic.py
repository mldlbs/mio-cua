"""Deterministic recovery: known failure modes act WITHOUT the LLM.

This is the de-modeling half of recovery. For well-known failures mio-cua must
execute a concrete action (Esc / focus window / scroll) instead of asking the
model to "think again". These tests pin that contract.
"""

import types

from mio_cua.runtime.belief import BeliefState
from mio_cua.runtime.recovery import RecoveryManager


def _robs(affordances=()):
    return types.SimpleNamespace(affordances=list(affordances))


def _search_aff():
    return types.SimpleNamespace(kind="search")


def test_context_menu_recovers_with_esc():
    rm = RecoveryManager()
    assert rm.recover_actions("context_menu", BeliefState(), _robs()) == [
        ("key", {"keys": "esc"})
    ]


def test_focus_lost_recovers_with_focus_window():
    belief = BeliefState({"app": "微信", "keyword": "测试"})
    rm = RecoveryManager()
    assert rm.recover_actions("focus_lost", belief, _robs()) == [
        ("focus_window", {"title": "微信"})
    ]


def test_focus_lost_without_target_app_is_noop():
    rm = RecoveryManager()
    assert rm.recover_actions("focus_lost", BeliefState({}), _robs()) == []


def test_target_invisible_recovers_with_scroll():
    rm = RecoveryManager()
    assert rm.recover_actions("target_invisible", BeliefState(), _robs()) == [
        ("scroll", {"direction": "down", "amount": 3})
    ]


def test_scroll_no_progress_reverses_when_fresh():
    belief = BeliefState()
    belief.scroll_stall = 0
    rm = RecoveryManager()
    assert rm.recover_actions("scroll_no_progress", belief, _robs()) == [
        ("scroll", {"direction": "up", "amount": 2})
    ]


def test_scroll_no_progress_defers_to_planner_when_stalled_and_searchable():
    belief = BeliefState()
    belief.scroll_stall = 3
    rm = RecoveryManager()
    # stalled + search available -> no deterministic action (planner gets hints)
    assert rm.recover_actions("scroll_no_progress", belief, _robs([_search_aff()])) == []


def test_apply_recovery_executes_actions_via_registry():
    calls = []

    class _Reg:
        def call(self, name, params, ctx):
            calls.append((name, params))
            return None

    rm = RecoveryManager(registry=_Reg())
    ok = rm.apply_recovery("context_menu", BeliefState(), _robs(), ctx=object())
    assert ok is True
    assert calls == [("key", {"keys": "esc"})]


def test_apply_recovery_no_registry_is_safe():
    rm = RecoveryManager(registry=None)
    assert rm.apply_recovery("context_menu", BeliefState(), _robs(), ctx=object()) is False
