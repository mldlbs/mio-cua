from mio_cua.perception.merger import _overlaps, merge
from mio_cua.models.element import Element


def _el(i, bbox, source):
    return Element(id=i, source=source, text=f"t{i}", bbox=bbox)


def test_overlaps_true():
    assert _overlaps((0, 0, 100, 100), (40, 40, 100, 100), ratio=0.3)


def test_overlaps_false():
    assert not _overlaps((0, 0, 10, 10), (100, 100, 10, 10), ratio=0.5)


def test_merge_removes_duplicates_and_renumbers():
    uia = [_el(0, (0, 0, 100, 50), "uia"), _el(1, (300, 300, 50, 50), "uia")]
    ocr = [_el(0, (0, 0, 100, 50), "ocr"), _el(1, (500, 500, 30, 30), "ocr")]
    merged = merge(ocr, uia)
    # overlapping one deduped, uia kept; other ocr appended
    assert len(merged) == 3
    ids = [e.id for e in merged]
    assert ids == [0, 1, 2]
    sources = [e.source for e in merged]
    assert sources[0] == "uia"


def _txtel(i, bbox, source, text):
    return Element(id=i, source=source, text=text, bbox=bbox)


def test_merge_keeps_ocr_digit_over_uia_chinese_label():
    # Calculator digit key: UIA exposes the localized name ("一"), OCR the
    # on-screen glyph ("7"). The OCR digit must survive the merge so the model
    # can target it.
    uia = [_txtel(0, (100, 100, 127, 48), "uia", "一")]
    ocr = [_txtel(1, (105, 110, 14, 18), "ocr", "7")]
    merged = merge(ocr, uia)
    assert len(merged) == 2
    texts = {e.text for e in merged}
    assert "7" in texts
    assert "一" in texts


def test_merge_keeps_uia_when_ocr_ascii_matches_uia_text():
    # Same text on both sides -> keep UIA (stable), no duplication.
    uia = [_txtel(0, (100, 100, 100, 50), "uia", "OK")]
    ocr = [_txtel(1, (105, 105, 20, 20), "ocr", "OK")]
    merged = merge(ocr, uia)
    assert len(merged) == 1
    assert merged[0].source == "uia"


def test_merge_keeps_ocr_when_uia_text_empty():
    # UIA container with no label -> OCR text is the only readable one.
    uia = [_txtel(0, (0, 0, 100, 50), "uia", "")]
    ocr = [_txtel(1, (5, 5, 30, 20), "ocr", "123")]
    merged = merge(ocr, uia)
    assert len(merged) == 2
    assert any(e.source == "ocr" and e.text == "123" for e in merged)


def test_merge_keeps_uia_for_non_ascii_ocr_overlap():
    # OCR text is non-ASCII (e.g. a glyph) -> keep the UIA label.
    uia = [_txtel(0, (0, 0, 100, 50), "uia", "Backspace")]
    ocr = [_txtel(1, (5, 5, 30, 20), "ocr", "⌫")]
    merged = merge(ocr, uia)
    assert len(merged) == 1
    assert merged[0].source == "uia"


def test_merge_ids_stable_when_uia_enumeration_order_changes():
    # UIA enumeration order varies frame to frame; ids must follow screen
    # position so the same physical button keeps the same id.
    def build(order):
        # 4 calculator-style buttons in a grid; OCR digits overlap UIA labels.
        uia = []
        for i, (pos, label) in enumerate(order):
            uia.append(_txtel(i, pos, "uia", label))
        ocr = [
            _txtel(9, (0, 0, 10, 10), "ocr", "7"),
            _txtel(10, (100, 0, 10, 10), "ocr", "8"),
            _txtel(11, (0, 100, 10, 10), "ocr", "4"),
            _txtel(12, (100, 100, 10, 10), "ocr", "5"),
        ]
        return merge(ocr, uia)

    pos_a = [(0, 0, 50, 40), (100, 0, 50, 40), (0, 100, 50, 40), (100, 100, 50, 40)]
    pos_b = [(100, 100, 50, 40), (0, 100, 50, 40), (100, 0, 50, 40), (0, 0, 50, 40)]
    labels = ["一", "二", "四", "五"]  # UIA localized names
    a = {e.text: e.id for e in build(list(zip(pos_a, labels)))}
    b = {e.text: e.id for e in build(list(zip(pos_b, labels)))}
    # "8" (top-right button) keeps the same id in both frames
    assert a["8"] == b["8"]
    # ids are unique and in 0..N-1
    assert sorted(a.values()) == list(range(len(a)))
    assert sorted(b.values()) == list(range(len(b)))
