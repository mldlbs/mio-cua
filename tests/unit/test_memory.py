from mio_cua.scene.memory import SceneMemory
from mio_cua.scene import build_scene
from mio_cua.models.element import Element


def _scene(elements, active_window="Calculator"):
    return build_scene(elements, active_window)


def _els(digits, display=None):
    els = []
    for i, d in enumerate(digits):
        els.append(Element(i, "ocr", text=d, role="text",
                           bbox=(100, 100 + i * 30, 40, 20), visible=True))
    if display is not None:
        els.append(Element(len(digits), "uia", text=display, role="text",
                           bbox=(100, 10, 400, 80), visible=True))
    return els


def test_memory_accumulates_seen_texts():
    mem = SceneMemory()
    mem.push(_scene(_els(["12", "34", "56"])))
    mem.push(_scene(_els(["12", "34", "56"])))
    s = mem.summarize()
    assert "12" in s
    assert "34" in s
    assert "56" in s


def test_memory_tracks_display_change():
    mem = SceneMemory()
    mem.push(_scene(_els(["0"], display="显示为 0")))
    mem.push(_scene(_els(["7"], display="显示为 7")))
    assert "显示为 7" in mem.display_value or "7" in mem.display_value


def test_memory_summarize_recent_actions():
    mem = SceneMemory()
    mem.push(_scene(_els(["12"])))
    s = mem.summarize(recent_actions=["click", "type", "launch"])
    assert "click" in s
    assert "launch" in s


def test_memory_ignores_short_noise():
    mem = SceneMemory()
    mem.push(_scene(_els(["-", "!", "ok"])))
    s = mem.summarize()
    assert "ok" in s
    assert "!" not in s


def test_memory_frame_cap():
    mem = SceneMemory(max_frames=2)
    for i in range(5):
        mem.push(_scene(_els([str(i)])))
    assert len(mem.frames) <= 2
