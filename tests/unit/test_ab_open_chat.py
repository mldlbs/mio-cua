"""Hard gate for opening a chat: unique exact match, or fail closed.

Every failure mode below must stop the flow BEFORE typing/clicking in a real
chat, so each test asserts the refusal (index is None / ok is False), not just
a happy path.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.ab.open_chat import (  # noqa: E402
    find_search_box,
    foreground_ok,
    select_unique_match,
    verify_open,
)

TARGET = "文件传输助手"


# ── uniqueness ──

def test_exact_single_match_is_accepted():
    idx, why = select_unique_match(["超图-李现玲", TARGET, "狼王"], TARGET)
    assert idx == 1
    assert "unique" in why


def test_zero_match_is_refused():
    idx, why = select_unique_match(["超图-李现玲", "狼王"], TARGET)
    assert idx is None
    assert "no exact match" in why


def test_multiple_exact_matches_are_refused():
    idx, why = select_unique_match([TARGET, "狼王", TARGET], TARGET)
    assert idx is None
    assert "multiple" in why


def test_truncated_row_is_refused_even_with_a_valid_match():
    # a sibling that only shows a prefix means the list cannot be trusted
    idx, why = select_unique_match([TARGET, "文件传输助"], TARGET)
    assert idx is None
    assert "truncated" in why


def test_ellipsis_row_is_refused():
    idx, why = select_unique_match([TARGET, "文件传输..."], TARGET)
    assert idx is None
    assert "truncated" in why


def test_whitespace_only_difference_still_matches():
    idx, _ = select_unique_match(["文件 传输助手"], TARGET)
    assert idx == 0


def test_similar_name_is_not_a_match():
    idx, why = select_unique_match(["文件传输助手2", "文件传输助手（旧）"], TARGET)
    assert idx is None


# ── search box ──

def _node(text, bbox):
    return ("text", text, bbox)


def test_search_box_found_by_placeholder():
    rect = (700, 320, 1350, 800)
    nodes = [_node("Q搜索", (840, 360, 150, 28)), _node("狼王", (840, 500, 80, 24))]
    box = find_search_box(nodes, rect)
    assert box == (840, 360, 150, 28)


def test_search_box_missing_is_none():
    rect = (700, 320, 1350, 800)
    nodes = [_node("狼王", (840, 500, 80, 24))]
    assert find_search_box(nodes, rect) is None


def test_search_box_outside_the_top_band_is_ignored():
    rect = (700, 320, 1350, 800)
    nodes = [_node("搜索", (840, 900, 150, 28))]      # too low: a message, not the box
    assert find_search_box(nodes, rect) is None


# ── foreground / identity ──

def test_foreground_requires_the_right_window_and_process():
    assert foreground_ok("微信", "weixin", "微信")[0] is True
    assert foreground_ok("企业微信", "wxwork", "微信")[0] is False
    assert foreground_ok("微信", "opencode", "微信")[0] is False
    assert foreground_ok("", "", "微信")[0] is False


def test_post_open_title_mismatch_is_refused():
    ok, why = verify_open("微信ClawBot AI", TARGET)
    assert ok is False
    assert "!=" in why


def test_post_open_title_match_is_accepted():
    ok, _ = verify_open("文件传输助手", TARGET)
    assert ok is True


def test_post_open_prefix_is_refused():
    """Close enough is not enough at the last gate before typing."""
    ok, _ = verify_open("文件传输助", TARGET)
    assert ok is False


def test_empty_title_is_refused():
    assert verify_open("", TARGET)[0] is False
