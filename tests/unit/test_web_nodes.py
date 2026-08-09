from mio_cua.models.element import Element
from mio_cua.scene import build_scene
from mio_cua.scene.graph import SceneNode


def test_build_scene_with_web_nodes():
    els = [Element(0, "uia", text="OK", role="button", bbox=(0, 0, 50, 20))]
    web = [
        SceneNode(id=10001, type="button", bbox=(100, 100, 80, 30),
                  text="Sign Up", semantic="Sign Up", source="web",
                  state={"enabled": True, "visible": True, "interactive": True}),
        SceneNode(id=10002, type="text", bbox=(100, 200, 200, 20),
                  text="Welcome", semantic="Welcome", source="web",
                  state={"enabled": True, "visible": True, "interactive": False}),
    ]
    scene = build_scene(els, "Chrome - example.com", web_nodes=web)
    # both desktop node and web nodes present
    ids = {n.id for n in scene.nodes}
    assert 0 in ids  # desktop element id preserved
    assert 10001 in ids
    assert 10002 in ids
    # only the interactive web node gets a click affordance
    click_ids = {a.node_id for a in scene.affordances if a.action == "click"}
    assert 10001 in click_ids
    assert 10002 not in click_ids


def test_build_scene_web_nodes_empty():
    els = [Element(0, "uia", text="OK", role="button", bbox=(0, 0, 50, 20))]
    scene = build_scene(els, "Notepad", web_nodes=[])
    assert all(n.id < 10000 for n in scene.nodes)
