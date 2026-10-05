from mio_cua.scene import build_scene, analyze_regions
from mio_cua.scene.regions import regions_summary
from mio_cua.scene.graph import Region


def test_regions_summary_filters_noise():
    regions = [
        Region(kind="title", bbox=(0, 0, 100, 20), confidence=0.9),
        Region(kind="text", bbox=(0, 30, 200, 50), confidence=0.85),
        Region(kind="figure", bbox=(0, 100, 300, 150), confidence=0.8),
        Region(kind="__noise__", bbox=(0, 0, 10, 10), confidence=0.9),
    ]
    s = regions_summary(regions)
    assert "title" in s
    assert "text" in s
    assert "figure" in s
    assert "__noise__" not in s


def test_build_scene_accepts_regions():
    from mio_cua.models.element import Element
    els = [Element(0, "uia", text="OK", role="button", bbox=(0, 0, 50, 20))]
    regions = [Region(kind="text", bbox=(0, 0, 100, 50), confidence=0.9)]
    scene = build_scene(els, "window", regions=regions)
    assert len(scene.regions) == 1
    assert scene.regions[0].kind == "text"


def test_build_scene_empty_regions():
    from mio_cua.models.element import Element
    els = [Element(0, "uia", text="OK", role="button", bbox=(0, 0, 50, 20))]
    scene = build_scene(els, "window")
    assert scene.regions == []


def test_analyze_regions_handles_missing_dependency(monkeypatch):
    # Simulate rapid_layout not being installed: analyze should return [].
    import mio_cua.scene.regions as regions_mod

    def _fake_load():
        return None

    monkeypatch.setattr(regions_mod, "_load", _fake_load)
    assert analyze_regions(None) == []
