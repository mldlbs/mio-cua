"""Unit tests for the runtime web-chat driver (mio_cua.web_chat).

The driver is the runtime counterpart of trace/record_chatgpt_multiturn.py: the
same recognition / layout / extraction / stitching rules, but site comes as a
parameter and the anchor is the prompt's own head. Only the pure parts are
tested here -- send/settle need a live browser.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import mio_cua.web_chat as wc  # noqa: E402

DS_COMPOSER = [1028, 1156, 775, 60]      # -> band 968..1863, floor 1156
CG_COMPOSER = [1033, 711, 153, 26]       # -> band 633..1586, floor 711


def node(text, bbox, type_="text"):
    return {"type": type_, "text": text, "bbox": bbox}


def obs(nodes, process="chrome"):
    return SimpleNamespace(scene_nodes=nodes, active_process=process)


def ds_page(*extra):
    return [node("·", DS_COMPOSER, "input"), *extra]


def cg_page(*extra):
    return [node("有问题，随便问", CG_COMPOSER, "input"), *extra]


# ── recognition ──

def test_looks_like_deepseek_by_url():
    assert wc.looks_like(obs([node("chat.deepseek.com/a/chat", [458, 224, 1473, 24])]), "deepseek")


def test_looks_like_needs_the_owning_process():
    """Electron apps share Chrome's window class; only a real browser counts."""
    page = [node("chat.deepseek.com", [458, 224, 1473, 24])]
    assert wc.looks_like(obs(page, process="opencode"), "deepseek") is False


def test_looks_like_chatgpt_markers_are_not_enough_alone():
    page = [node("有问题，随便问", CG_COMPOSER)]
    assert wc.looks_like(obs(page), "chatgpt") is False
    page.append(node("也可能会犯错", [1100, 900, 160, 20]))
    assert wc.looks_like(obs(page), "chatgpt") is True


def test_looks_like_rejects_the_wrong_site():
    page = [node("chat.deepseek.com", [458, 224, 1473, 24])]
    assert wc.looks_like(obs(page), "chatgpt") is False


# ── layout / composer ──

def test_deepseek_layout_excludes_the_outline_panel():
    """60px padding, not ChatGPT's 400: the outline entries sit at x~2011."""
    nodes = ds_page(node("R400 我们来聊聊现实的公共议题", [2011, 678, 175, 17]))
    left, right, floor = wc.layout(wc._node_tuples(obs(nodes)), "deepseek")
    assert (left, right, floor) == (968, 1863, 1156)


def test_find_composer_skips_markdown_quotes():
    """Quote rows come back as type=input with a 753x48 box and a full
    sentence; the real composer is the short-texted one."""
    quote = node("这是一整句话的引用内容", [1039, 600, 753, 48], "input")
    cx, cy = wc.find_composer(wc._node_tuples(obs(ds_page(quote))), "deepseek")
    assert (cx, cy) == (1415, 1186)


# ── extraction ──

TOK = "请解释一下"


def test_reply_is_the_text_below_our_message():
    msg = node(TOK + " 这件事的原理。", [1143, 631, 621, 44])
    first = node("这是答复第一句。", [1039, 785, 753, 20])
    last = node("最后一句。", [1039, 815, 753, 20])
    text, _why, _meta = wc.extract_last_reply(
        obs(ds_page(msg, first, last)), [TOK], prompt=TOK + " 这件事的原理。", site="deepseek"
    )
    assert "答复第一句" in text
    assert "最后一句" in text
    assert TOK not in text.split("答复")[0]


def test_reply_skips_control_chrome():
    msg = node(TOK + " 原理。", [1143, 631, 621, 44])
    reply = node("真正的答复。", [1039, 785, 753, 20])
    copy_btn = node("C", [1071, 815, 28, 28])
    speak = node("朗读", [1185, 815, 28, 28])
    text, _why, _meta = wc.extract_last_reply(
        obs(ds_page(msg, reply, copy_btn, speak)), [TOK], prompt=TOK + " 原理。", site="deepseek"
    )
    assert text == "真正的答复。"


def test_reply_keeps_late_lines_despite_tree_order():
    """A trailing button listed BEFORE the reply's later lines must not cut them."""
    msg = node(TOK + " 原理。", [1143, 719, 621, 44])
    head = node("开头正文。", [1039, 829, 753, 120])
    tail = node("树序靠后的结尾续行。", [1039, 997, 753, 76])
    button = node("C", [1071, 1089, 28, 28])
    text, _why, _meta = wc.extract_last_reply(
        obs(ds_page(msg, head, button, tail)), [TOK], prompt=TOK + " 原理。", site="deepseek"
    )
    assert "结尾续行" in text


def test_reply_drops_the_wrapped_prompt_echo():
    prompt = TOK + " 越详细越好，最后请把这句话原样附上"
    msg = node(prompt, [1143, 631, 621, 44])
    echo = node("最后请把这句话原样附上", [1039, 785, 753, 20])
    real = node("真正的回答。", [1039, 815, 753, 20])
    text, _why, _meta = wc.extract_last_reply(
        obs(ds_page(msg, echo, real)), [TOK], prompt=prompt, site="deepseek"
    )
    assert "原样附上" not in text
    assert "真正的回答" in text


# ── delivery ──

def test_sent_seen_ignores_the_composer_draft():
    placeholder = node("·", DS_COMPOSER, "input")
    draft = node(TOK + " 这件事的原理。", DS_COMPOSER, "input")
    assert wc._sent_seen(obs([placeholder, draft]), TOK, "deepseek") is False


def test_sent_seen_accepts_a_bubble():
    bubble = node(TOK + " 这件事的原理。", [1143, 631, 621, 44])
    assert wc._sent_seen(obs(ds_page(bubble)), TOK, "deepseek") is True


# ── stitching ──

def test_stitch_lines_merges_overlapping_views():
    assert wc._stitch_lines(["d", "e", "f"], ["a", "b", "c", "d", "e"]) == \
        ["a", "b", "c", "d", "e", "f"]


# ── argument validation (no UI touched) ──

def test_ask_rejects_unknown_site():
    with pytest.raises(ValueError):
        wc.ask(site="bing", prompt="hi")


def test_ask_rejects_empty_prompt():
    with pytest.raises(ValueError):
        wc.ask(site="deepseek", prompt="   ")
