"""A container must never swallow the text inside it.

Live bug (2026-10-28): on WeChat, OCR found 18 texts but merge kept 4 -- the
full-window UIA root (text "微信") and its pane (text "MMUIRenderSubWindowHW")
overlapped every OCR box, so the old "overlap => keep UIA" rule dropped them.
The search box and conversation title never reached the scene, which made the
agent blind to the app and blocked the A/B harness.

The rule now: dedupe only with evidence of the SAME control (comparable size +
substantial overlap), and containers never participate.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mio_cua.models.element import Element  # noqa: E402
from mio_cua.perception.merger import merge  # noqa: E402


def ocr(text, bbox):
    return Element(id=0, source="ocr", text=text, role="text", bbox=bbox)


def uia(text, bbox, role="button"):
    return Element(id=0, source="uia", text=text, role=role, bbox=bbox)


def texts(merged):
    return [e.text for e in merged if (e.text or "").strip()]


# 1) a large container must not eat the OCR text inside it
def test_large_container_keeps_all_inner_ocr_texts():
    root = uia("微信", (0, 0, 1200, 800), role="window")
    pane = uia("MMUIRenderSubWindowHW", (10, 10, 1180, 780), role="pane")
    inner = [ocr("搜索", (100, 60, 120, 24)),
             ocr("文件传输助手", (100, 200, 160, 24)),
             ocr("你好", (400, 500, 80, 22))]
    merged = merge(inner, [root, pane])
    for e in inner:
        assert e.text in texts(merged), e.text
    assert root.metadata.get("container") is True
    assert pane.metadata.get("container") is True


# 2) same control, comparable size -> dedupe (no duplicate text)
def test_same_control_with_similar_size_is_deduped():
    o = ocr("确定", (100, 100, 60, 24))
    u = uia("确定", (102, 101, 58, 23))
    merged = merge([o], [u])
    assert texts(merged).count("确定") == 1
    # the UIA element is the stable one that survives
    assert [e.source for e in merged if e.text == "确定"] == ["uia"]


# 3) two adjacent, partially overlapping texts -> keep both
def test_partially_overlapping_texts_are_not_merged():
    a = ocr("正文第一行", (100, 100, 200, 22))
    b = uia("正文第二行", (160, 112, 200, 22), role="text")   # ~30% overlap
    merged = merge([a], [b])
    assert "正文第一行" in texts(merged)
    assert "正文第二行" in texts(merged)


# 4) container text differs from the inner OCR -> inner text survives
def test_container_text_does_not_replace_inner_text():
    pane = uia("MMUIRenderSubWindowHW", (0, 0, 1000, 700), role="pane")
    o = ocr("微信ClawBot AI", (300, 40, 180, 24))
    merged = merge([o], [pane])
    assert "微信ClawBot AI" in texts(merged)
    assert "MMUIRenderSubWindowHW" in texts(merged)      # container metadata kept


# 5) pure UIA / pure OCR unchanged
def test_pure_uia_scene_is_unchanged():
    els = [uia("按钮", (10, 10, 40, 24)), uia("输入", (60, 10, 200, 24), role="edit")]
    merged = merge([], els)
    assert [e.text for e in merged] == ["按钮", "输入"]


def test_pure_ocr_scene_is_unchanged():
    els = [ocr("甲", (10, 10, 20, 20)), ocr("乙", (40, 10, 20, 20))]
    merged = merge(els, [])
    assert [e.text for e in merged] == ["甲", "乙"]


# extra: a same-sized UIA with no text still loses to OCR (calculator digits)
def test_ascii_glyph_wins_over_localized_name():
    o = ocr("7", (10, 10, 18, 20))
    u = uia("一", (10, 10, 20, 22))
    merged = merge([o], [u])
    assert "7" in texts(merged)


# extra: ids stay stable across frames (sorted by position)
def test_ids_are_position_based_after_merge():
    root = uia("窗口", (0, 0, 800, 600), role="window")
    a = ocr("上", (100, 100, 40, 20))
    b = ocr("下", (100, 300, 40, 20))
    merged_a = merge([a, b], [root])
    order_a = [(e.text, e.id) for e in merged_a]
    # same inputs, reversed enumeration order -> same ids
    merged_b = merge([b, a], [root])
    order_b = [(e.text, e.id) for e in merged_b]
    assert order_a == order_b
