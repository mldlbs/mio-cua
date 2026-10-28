"""Judges must be objective: a real failure is caught, a success is not faked.

The acceptance rule for the A/B harness is "inject one failure and the judge
must recognise it, never report a false success", so every test below pairs a
passing case with an injected failure.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.ab.judge import (  # noqa: E402
    judge_message_sent,
    judge_no_wrong_click,
    judge_obstruction_cleared,
    judge_terminated,
    judge_two_step,
)


# ── T1 ──

def test_t1_success_when_last_message_matches():
    v = judge_message_sent(["旧消息", "你好，世界"], "你好，世界")
    assert v.ok is True


def test_t1_failure_when_message_not_sent():
    """Injected failure: the send never happened."""
    v = judge_message_sent(["旧消息"], "你好，世界")
    assert v.ok is False
    assert "!=" in v.detail


def test_t1_failure_when_a_later_message_displaced_it():
    v = judge_message_sent(["你好，世界", "别的话"], "你好，世界")
    assert v.ok is False


def test_t1_ignores_blank_and_whitespace_differences():
    v = judge_message_sent(["  你好，   世界  "], "你好，世界")
    assert v.ok is True


# ── T2 ──

def _click(step, target, success=True, violated=False, reason="ok"):
    return {"step": step, "action": "click", "target": target,
            "result_success": success, "target_violated": violated, "reason": reason}


def test_t2_success_when_only_blocked_actions():
    traj = [_click(1, "另一个群", success=False, violated=False,
                   reason="blocked: target invisible")]
    v = judge_no_wrong_click(traj, "目标群")
    assert v.ok is True
    assert v.evidence["blocked"] == 1


def test_t2_failure_on_executed_wrong_click():
    """Injected failure: the agent clicked a similar name."""
    v = judge_no_wrong_click([_click(1, "另一个群")], "目标群")
    assert v.ok is False
    assert v.evidence["misclicks"][0]["target"] == "另一个群"


def test_t2_failure_on_wrong_click_even_if_marked_successful_elsewhere():
    v = judge_no_wrong_click(
        [_click(1, "目标群 - 旧会话", success=True),
         _click(2, "另一个群", success=True)],
        "目标群",
    )
    assert v.ok is False
    assert len(v.evidence["misclicks"]) == 1


def test_t2_ignores_failed_clicks_that_hit_nothing():
    v = judge_no_wrong_click([_click(1, "", success=False)], "目标群")
    assert v.ok is True


def test_t2_termination_is_part_of_the_criterion():
    assert judge_terminated("FAIL").ok is True
    assert judge_terminated("SUCCESS").ok is True
    assert judge_terminated("TIMEOUT").ok is False


# ── T3 ──

def test_t3_success_when_menu_dismissed():
    v = judge_obstruction_cleared(["window", "pane", "text"], had_menu=True)
    assert v.ok is True


def test_t3_failure_when_menu_still_open():
    """Injected failure: Esc never happened."""
    v = judge_obstruction_cleared(["window", "menu", "text"], had_menu=True)
    assert v.ok is False


def test_t3_failure_when_no_menu_was_injected():
    """A run that never reproduced the obstruction proves nothing."""
    v = judge_obstruction_cleared(["window"], had_menu=False)
    assert v.ok is False
    assert "never injected" in v.detail or "ever injected" in v.detail


# ── T4 ──

def test_t4_success_when_message_appears_after_submit():
    v = judge_two_step(["旧消息"], ["旧消息", "提交内容"], "提交内容")
    assert v.ok is True


def test_t4_failure_when_message_was_already_there():
    """Injected failure: the submit step did nothing."""
    v = judge_two_step(["提交内容"], ["提交内容"], "提交内容")
    assert v.ok is False


def test_t4_failure_when_wrong_text_submitted():
    v = judge_two_step(["旧消息"], ["旧消息", "别的内容"], "提交内容")
    assert v.ok is False

def test_title_matches_tolerates_ocr_spacing_and_split_names():
    from experiments.ab.reset import title_matches
    assert title_matches("文件传输助手", "文件传输助手") is True
    assert title_matches("文件 传输助手", "文件传输助手") is True
    assert title_matches("文件传输助", "文件传输助手") is True
    assert title_matches("微信ClawBot AI", "文件传输助手") is False
    assert title_matches("", "文件传输助手") is False      # unknown must fail closed
