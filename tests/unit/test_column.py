"""Unit tests for the reusable column reader (mio_cua.perception.column).

The multi-turn recorder learned these rules live; the reader is now the single
place they live, so they are pinned here directly rather than only through the
scenario wrapper.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mio_cua.perception import column  # noqa: E402


def node(text, bbox, type_="text"):
    return (type_, text, bbox)


def band(left=0, right=2000, top=200, floor=1156):
    def _in_band(bbox):
        x, y = bbox[0], bbox[1]
        return left <= x <= right and y > top
    return _in_band


def ident(text, tok):
    t = (text or "").strip()
    return t.startswith(tok) and not t.endswith(tok)


def noise(text):
    return (text or "").strip() in ("C", "朗读")


def read(nodes, **kw):
    kw.setdefault("in_band", band())
    kw.setdefault("is_identity", ident)
    kw.setdefault("is_noise", noise)
    return column.read_column(nodes, **kw)


def test_anchor_prefers_short_rows_over_a_tall_echoing_container():
    nodes = [
        node("R400 我们来聊聊", [1143, 719, 621, 44]),
        node("R400 有修正。答复正文。", [1039, 829, 753, 188]),
    ]
    r = read(nodes, tokens=["R400"])
    assert r.anchored is True
    assert r.boundary_y == 719
    assert "有修正" in r.text


def test_fallback_opens_below_a_previous_badge():
    nodes = [
        node("R399", [1039, 595, 41, 20]),
        node("本轮答复。", [1039, 665, 753, 188]),
        node("R400", [1439, 1053, 45, 20]),
    ]
    r = read(nodes, tokens=["R400"], stop_token="R399")
    assert r.anchored is False
    assert r.boundary_y >= 595
    assert r.text.startswith("本轮答复")
    assert r.text.endswith("R400")


def test_tree_order_is_ignored_and_noise_never_truncates():
    nodes = [
        node("R400 回顾", [1143, 719, 621, 44]),
        node("开头。", [1039, 830, 753, 20]),
        node("R400", [1439, 1053, 45, 20]),
        node("C", [1071, 1089, 28, 28]),
        node("结尾续行。", [1039, 997, 753, 76]),   # listed AFTER the noise
    ]
    r = read(nodes, tokens=["R400"])
    assert r.text == "开头。 结尾续行。 R400"


def test_tall_container_dedups_lines_but_keeps_the_badge():
    nodes = [
        node("R400 聊聊", [1143, 719, 621, 44]),
        node("第一段。第二段。", [1039, 785, 753, 244]),
        node("第一段。", [1039, 842, 753, 20]),
        node("R400", [1439, 1050, 45, 20]),          # inside the tall span
    ]
    r = read(nodes, tokens=["R400"])
    assert r.text == "第一段。第二段。 R400"


def test_badge_below_the_floor_is_kept():
    nodes = [
        node("R400 回顾", [1143, 719, 621, 44]),
        node("答复正文。", [1039, 900, 753, 120]),
        node("R400", [1013, 1166, 41, 20]),          # floor is 1156
    ]
    r = read(nodes, tokens=["R400"], floor=1156)
    assert r.text.endswith("R400")


def test_button_text_double_render_counts_once():
    nodes = [
        node("R400 回顾", [1143, 631, 621, 44]),
        node("答复第一句。", [1039, 785, 753, 28], type_="button"),
        node("答复第一句。", [1039, 789, 753, 20]),
    ]
    r = read(nodes, tokens=["R400"])
    assert r.text.count("答复第一句。") == 1


def test_prompt_echo_row_is_skipped():
    prompt = "R400 回顾这五轮（回答最后请原样带上我消息开头的编号）"
    nodes = [
        node(prompt, [1143, 631, 621, 44]),
        node("回答最后请原样带上我消息开头的编号", [1039, 785, 753, 20]),
        node("我的最终看法是……", [1039, 820, 753, 20]),
    ]
    r = read(nodes, tokens=["R400"], prompt=prompt)
    assert "原样带上" not in r.text
    assert "最终看法" in r.text


def test_stitch_lines_merges_overlap_and_tolerates_spacing():
    assert column.stitch_lines(["d", "e", "f"], ["a", "b", "c", "d", "e"]) == \
        ["a", "b", "c", "d", "e", "f"]
    assert column.stitch_lines(["c", "d"], ["a", "b"]) == ["a", "b", "c", "d"]
    out = column.stitch_lines(["答复 第一句。", "第二句。"], ["开头。", "答复第一句。"])
    assert out == ["开头。", "答复 第一句。", "第二句。"]


def test_column_read_text_joins_pieces():
    r = column.ColumnRead(pieces=[(0, 0, "a", 1), (0, 0, "b", 1)])
    assert r.text == "a b"
