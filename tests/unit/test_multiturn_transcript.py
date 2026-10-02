"""Extraction regressions for the multi-turn recorder (DeepSeek).

The 2026-10-02 DeepSeek run took three live attempts; every miss below is a
failure mode that actually happened and cost a turn, so these fixtures are the
only thing standing between the next edit and a repeat:

  * anchor: our bubble can scroll out of the viewport while the reply is
    bottom-anchored, so extraction must fall back to the previous turn's
    boundary -- and must not let a reply that ECHOES the token as a prefix
    ("R400 有修正…") steal the anchor from the real bubble
  * band: DeepSeek renders the trailing badge only at stream end, and the UIA
    tree order is NOT y order -- a trailing 'C' node listed before the reply's
    lines once truncated a 700-char answer to 95 chars
  * dedup: the same reply arrives as one tall container AND as its lines;
    dropping the covered lines must never drop the exact token badge, or
    ``tagged`` reads 0 on a correct extraction
  * delivery: an Enter that did not send leaves the whole draft in the input,
    where the token trivially matches -- ``_sent_seen`` must ignore inputs
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "trace"))

import record_chatgpt_multiturn as mt  # noqa: E402

# DeepSeek composer geometry from the live captures: a 775x60 input low on the
# page whose placeholder OCRs to one garbage character. _input_box turns this
# into the band (968..1863, floor 1156).
COMPOSER = [1028, 1156, 775, 60]


@pytest.fixture(autouse=True)
def deepseek(monkeypatch):
    monkeypatch.setattr(mt, "SITE", "deepseek")


def node(text, bbox, type_="text"):
    return {"type": type_, "text": text, "bbox": bbox}


def obs(nodes):
    return SimpleNamespace(scene_nodes=nodes)


def page(*extra):
    return [node("·", COMPOSER, "input"), *extra]


# ── anchor ──

def test_anchor_is_the_bubble_when_the_reply_echoes_the_token_as_prefix():
    """'R400 有修正…' is the answer, not our message: its tall container must
    not win the anchor and push its own head out of the band."""
    bubble = node("R400 我们来聊聊意识问题", [1143, 719, 621, 44])
    reply = node("R400 有修正。这是答复正文，从第一句开始。", [1039, 829, 753, 188])
    text, _why, meta = mt.extract_last_reply(obs(page(bubble, reply)), ["R400"])
    assert meta["user_y"] == 719
    assert "有修正" in text


def test_nothing_sent_yet_is_not_a_reply():
    text, why, _meta = mt.extract_last_reply(obs(page()), ["R400"])
    assert text == ""
    assert "no prose" in why


def test_bubble_scrolled_out_falls_back_to_previous_turn_boundary():
    """Our bubble left the viewport; the previous turn's badge is the band top
    and the reply below it is this turn's answer."""
    prev_badge = node("R399", [1039, 595, 41, 20])
    reply = node("这是本轮答复正文。", [1039, 665, 753, 188])
    badge = node("R400", [1439, 1053, 45, 20])
    text, why, _meta = mt.extract_last_reply(
        obs(page(prev_badge, reply, badge)), ["R400"], stop_token="R399"
    )
    assert "fallback band" in why
    assert "本轮答复正文" in text
    assert "R400" in text
    assert "R399" not in text


def test_first_turn_fallback_opens_at_the_viewport_top():
    reply = node("第一轮答复正文。", [1039, 254, 753, 188])
    badge = node("R400", [1439, 1053, 45, 20])
    text, why, meta = mt.extract_last_reply(obs(page(reply, badge)), ["R400"])
    assert "fallback band (top=200)" in why
    assert "第一轮答复正文" in text
    assert meta["user_y"] == 200


def test_previous_reply_body_stays_above_the_boundary():
    """The boundary is the previous badge, so the previous reply (which sits
    above it) must not leak into this turn's band."""
    prev_reply = node("R399 这是上一轮的答复正文。", [1039, 400, 753, 150])
    prev_badge = node("R399", [1039, 560, 41, 20])
    reply = node("本轮答复正文。", [1039, 665, 753, 188])
    text, _why, meta = mt.extract_last_reply(
        obs(page(prev_reply, prev_badge, reply)), ["R400"], stop_token="R399"
    )
    assert meta["user_y"] == 560
    assert "上一轮" not in text
    assert "本轮答复正文" in text


# ── band: tree order and noise ──

def test_tree_order_noise_does_not_truncate_the_reply():
    """The trailing 'C'/'朗读' rows can be listed BEFORE the reply's later
    lines; noise must be skipped, never used as a break."""
    bubble = node("R400 回顾这五轮讨论", [1143, 719, 621, 44])
    head = node("R400 有修正。开头正文。", [1039, 829, 753, 120])
    tail = node("树序里排在噪声之后的结尾续行。", [1039, 997, 753, 76])
    badge = node("R400", [1439, 1053, 45, 20])
    copy_btn = node("C", [1071, 1089, 28, 28])
    speak = node("朗读", [1185, 1089, 28, 28])
    # deliberately NOT y-sorted: the buttons sit before the tail in tree order
    nodes = page(bubble, head, badge, copy_btn, speak, tail)
    text, _why, meta = mt.extract_last_reply(obs(nodes), ["R400"])
    assert "结尾续行" in text
    assert text.rstrip().endswith("R400")
    assert meta["pieces"] == 3

# ── dedup ──

def test_tall_container_and_its_lines_are_not_double_counted():
    bubble = node("R400 聊聊旅行", [1143, 631, 621, 44])
    container = node("第一段。第二段。", [1039, 785, 753, 244])
    lines = [node("第一段。", [1039, 842, 753, 20]),
             node("第二段。", [1039, 871, 753, 20])]
    badge = node("R400", [1439, 1053, 45, 20])
    text, _why, _meta = mt.extract_last_reply(
        obs(page(bubble, container, *lines, badge)), ["R400"]
    )
    assert text == "第一段。第二段。 R400"


def test_inside_a_line_span_is_still_kept():
    """The badge often sits inside a tall line's bbox; the dedup exception must
    keep it, otherwise a correct extraction reports tagged=False."""
    bubble = node("R400 回顾", [1143, 719, 621, 44])
    line = node("整段正文都在这个高节点里。", [1039, 830, 753, 230])
    badge = node("R400", [1439, 1050, 45, 20])
    text, _why, _meta = mt.extract_last_reply(obs(page(bubble, line, badge)), ["R400"])
    assert "整段正文" in text
    assert text.rstrip().endswith("R400")


# ── prompt echo ──

def test_wrapped_prompt_row_is_not_mistaken_for_the_reply():
    """Turn 265 of the 100-turn run came back as the prompt's own second line."""
    prompt = "R400 回顾这五轮讨论，请给出你最终的看法（回答最后请原样带上我消息开头的编号）"
    bubble = node(prompt, [1143, 631, 621, 44])
    echo = node("回答最后请原样带上我消息开头的编号", [1039, 785, 753, 20])
    real = node("我的最终看法是……", [1039, 820, 753, 20])
    text, _why, _meta = mt.extract_last_reply(
        obs(page(bubble, echo, real)), ["R400"], prompt=prompt
    )
    assert "原样带上" not in text
    assert "最终看法" in text


# ── delivery ──

def test_delivered_bubble_counts_as_sent():
    bubble = node("R400 我们来聊聊", [1143, 631, 621, 44])
    assert mt._sent_seen(obs(page(bubble)), "R400") is True


def test_outline_entry_counts_as_sent():
    """The outline mirrors only messages that actually landed, so it proves
    delivery even when the bubble has scrolled out."""
    outline = node("R400 我们来聊聊意识问题", [2011, 678, 175, 17])
    assert mt._sent_seen(obs(page(outline)), "R400") is True


def test_composer_draft_is_not_delivery():
    """Enter failed: the whole prompt, token included, sits in the input."""
    placeholder = node("·", COMPOSER, "input")
    draft = node("R400 我们来聊聊意识问题", COMPOSER, "input")
    assert mt._sent_seen(obs([placeholder, draft]), "R400") is False


def test_no_composer_means_no_proof():
    """Without a layout we cannot separate transcript from composer."""
    bubble = node("R400 我们来聊聊", [1143, 631, 621, 44])
    assert mt._sent_seen(obs([bubble]), "R400") is False
