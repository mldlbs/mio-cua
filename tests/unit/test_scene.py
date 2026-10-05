from mio_cua.models.element import Element
from mio_cua.scene import build_scene
from mio_cua.scene.diff import diff as scene_diff
from mio_cua.scene.builder import NodeBuilder
from mio_cua.scene.relations import RelationBuilder
from mio_cua.scene.affordances import AffordanceBuilder


def _ocr_el(i, text, bbox, conf=0.9):
    return Element(id=i, source="ocr", text=text, role="text", bbox=bbox, confidence=conf)


def _uia_el(i, text, role, bbox, enabled=True, visible=True):
    return Element(id=i, source="uia", text=text, role=role, bbox=bbox,
                   enabled=enabled, visible=visible)


def _merged(*els):
    # mimic merge(): renumber by list index
    for i, e in enumerate(els):
        e.id = i
    return list(els)


def test_node_builder_fuses_digit_into_button():
    # UIA exposes the button with a localized name, OCR the glyph "7".
    merged = _merged(
        _uia_el(0, "一", "button", (100, 100, 127, 48)),
        _ocr_el(1, "7", (105, 110, 14, 18)),
    )
    nodes = NodeBuilder(merged).build()
    assert len(nodes) == 1
    n = nodes[0]
    assert n.type == "button"
    assert n.text == "7"  # OCR glyph wins over UIA localized name
    assert n.state["enabled"] is True
    assert n.id == 0  # keeps the UIA element id (tool-resolvable)


def test_node_builder_keeps_uia_text_when_ocr_absent():
    uia = _uia_el(0, "OK", "button", (0, 0, 50, 20))
    nodes = NodeBuilder([uia]).build()
    assert len(nodes) == 1
    assert nodes[0].text == "OK"
    assert nodes[0].type == "button"


def test_node_builder_standalone_ocr_becomes_text_node():
    ocr = _ocr_el(5, "hello", (0, 0, 40, 10))
    nodes = NodeBuilder([ocr]).build()
    assert len(nodes) == 1
    assert nodes[0].type == "text"
    assert nodes[0].text == "hello"
    assert nodes[0].id == 5  # id preserved


def test_node_builder_drops_invisible_uia():
    uia = _uia_el(0, "hidden", "button", (0, 0, 50, 20), visible=False)
    nodes = NodeBuilder([uia]).build()
    assert len(nodes) == 0


def test_relation_builder_finds_adjacency():
    a = _uia_el(0, "7", "button", (100, 100, 50, 50))
    b = _uia_el(1, "8", "button", (160, 100, 50, 50))
    c = _uia_el(2, "9", "button", (220, 100, 50, 50))
    nodes = NodeBuilder([a, b, c]).build()
    rels = RelationBuilder(nodes).build()
    kinds = {(r.source, r.target, r.kind) for r in rels}
    assert (0, 1, "leftOf") in kinds
    assert (1, 2, "leftOf") in kinds


def test_affordance_builder_generates_click_for_buttons():
    merged = _merged(
        _uia_el(0, "一", "button", (100, 100, 127, 48)),
        _ocr_el(1, "7", (105, 110, 14, 18)),
    )
    nodes = NodeBuilder(merged).build()
    rels = RelationBuilder(nodes).build()
    affordances, display_ids = AffordanceBuilder(nodes, rels).build()
    assert any(a.action == "click" and a.node_id == 0 for a in affordances)
    assert affordances[0].params.get("value") == "7"


def test_display_inference_finds_readout():
    merged = _merged(
        _uia_el(0, "显示为 0", "text", (100, 10, 400, 80)),
        _uia_el(1, "一", "button", (100, 200, 127, 48)),
        _uia_el(2, "二", "button", (100, 260, 127, 48)),
        _ocr_el(3, "0", (200, 20, 30, 20)),
    )
    nodes = NodeBuilder(merged).build()
    rels = RelationBuilder(nodes).build()
    affordances, display_ids = AffordanceBuilder(nodes, rels).build()
    assert len(display_ids) == 1
    # buttons below the display get a display expectation
    digit_aff = [a for a in affordances if a.node_id in (1, 2)]
    assert all(a.expected.get("display") for a in digit_aff)


def test_build_scene_end_to_end():
    merged = _merged(
        _uia_el(0, "一", "button", (100, 100, 127, 48)),
        _uia_el(1, "二", "button", (160, 100, 127, 48)),
        _uia_el(2, "显示为 0", "text", (100, 10, 400, 80)),
        _ocr_el(3, "7", (105, 110, 14, 18)),
        _ocr_el(4, "8", (165, 110, 14, 18)),
    )
    scene = build_scene(merged, active_window="Calculator")
    assert len(scene.nodes) == 3
    assert len(scene.affordances) >= 2
    assert len(scene.display_ids) == 1


def test_operator_button_expects_display_unchanged():
    # Pressing ×/÷/+/- does not change the display (it waits for the next
    # operand); the affordance must say so, or the model treats an unchanged
    # display as a missed click and repeats the operator.
    merged = _merged(
        _uia_el(0, "乘以", "button", (100, 300, 127, 48)),
        _uia_el(1, "显示为 0", "text", (100, 10, 400, 80)),
        _ocr_el(2, "×", (105, 310, 14, 18)),
    )
    scene = build_scene(merged, active_window="Calculator")
    op = [a for a in scene.affordances if a.node_id == 0][0]
    assert op.expected.get("display") == "unchanged"


def test_ocr_button_words_get_click_affordance():
    # Modern dialogs (Win11 save dialog) expose buttons only as OCR text; those
    # labels must still be clickable, while plain labels stay non-clickable.
    merged = _merged(
        _ocr_el(0, "保存(S)", (1041, 778, 45, 21)),
        _ocr_el(1, "取消", (1148, 779, 31, 19)),
        _ocr_el(2, "文件名(N):", (100, 673, 64, 20)),
        _ocr_el(3, "102.txt", (167, 671, 46, 22)),
        _ocr_el(4, "保存类型(I)：文本文档(*.txt)", (92, 702, 157, 17)),
    )
    nodes = NodeBuilder(merged).build()
    affs, _ = AffordanceBuilder(nodes, []).build()
    clickable = {a.node_id for a in affs if a.action == "click"}
    assert 0 in clickable, "保存(S) should be clickable"
    assert 1 in clickable, "取消 should be clickable"
    assert 2 not in clickable, "文件名(N): label should not be clickable"
    assert 3 not in clickable, "102.txt filename should not be clickable"
    assert 4 not in clickable, "保存类型 combobox label should not be clickable"


def test_dialog_field_label_marks_filename_box_typeable():
    # Win11 save dialogs expose the filename edit box only as OCR text; the
    # label 文件名(N): lets us infer the box is typeable.
    merged = _merged(
        _ocr_el(0, "文件名(N):", (100, 673, 64, 20)),
        _ocr_el(1, "hello wprld.txt", (167, 671, 94, 28)),
        _ocr_el(2, "保存(S)", (1041, 778, 45, 21)),
    )
    nodes = NodeBuilder(merged).build()
    affs, _ = AffordanceBuilder(nodes, []).build()
    typeable = {a.node_id for a in affs if a.action == "type"}
    assert 1 in typeable, "filename box should get a type affordance"
    assert 0 not in typeable, "label itself is not typeable"
    n1 = next(n for n in nodes if n.id == 1)
    assert n1.type == "input", "field node is marked editable in the scene"


def test_dialog_field_label_not_a_folder():
    # `Windows-SSD (C:)` is a folder row in the file list, not a field label;
    # it must not produce a type affordance.
    merged = _merged(
        _ocr_el(0, "Windows-SSD (C:)", (77, 597, 134, 23)),
        _ocr_el(1, "文本文档", (694, 602, 55, 18)),
        _ocr_el(2, "文件名(N):", (100, 673, 64, 20)),
        _ocr_el(3, "hello wprld.txt", (167, 671, 94, 28)),
    )
    nodes = NodeBuilder(merged).build()
    affs, _ = AffordanceBuilder(nodes, []).build()
    typeable = {a.node_id for a in affs if a.action == "type"}
    assert 3 in typeable
    assert 1 not in typeable, "folder name far to the right is not the field"


def test_scene_diff_detects_display_change():
    merged0 = _merged(
        _uia_el(0, "显示为 0", "text", (100, 10, 400, 80)),
        _uia_el(1, "一", "button", (100, 200, 127, 48)),
        _ocr_el(2, "0", (200, 20, 30, 20)),
    )
    merged1 = _merged(
        _uia_el(0, "显示为 7", "text", (100, 10, 400, 80)),
        _uia_el(1, "一", "button", (100, 200, 127, 48)),
        _ocr_el(2, "7", (200, 20, 30, 20)),
    )
    s0 = build_scene(merged0, active_window="Calculator")
    s1 = build_scene(merged1, active_window="Calculator")
    changes = scene_diff(s0, s1)
    kinds = [c.kind for c in changes]
    assert "text_changed" in kinds
