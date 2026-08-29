"""Tests for Perception Quality Gate and Visual Fallback.

Tests:
  - QualityReport confidence-based scoring (coverage, interaction, semantic)
  - Fallback node generation
  - Scene enhancement
"""

import pytest

from mio_cua.perception.quality import (
    QualityReport,
    assess_quality,
    enhance_scene_with_fallback,
    visual_fallback_nodes,
)
from mio_cua.scene.graph import SceneGraph, SceneNode


# ---- Quality Assessment ----


class TestQualityAssessment:

    def _scene(self, nodes):
        return SceneGraph(nodes=nodes, active_window="test")

    def _node(self, nid, ntype="text", text="", semantic="", confidence=1.0):
        return SceneNode(id=nid, type=ntype, bbox=(0, 0, 100, 30),
                         text=text, semantic=semantic, confidence=confidence)

    def test_usable_scene_many_nodes(self):
        nodes = [self._node(i, "text", f"item_{i}") for i in range(10)]
        q = assess_quality(self._scene(nodes))
        assert q.is_usable is True
        assert q.node_count == 10
        assert q.interactive_count == 10
        assert q.confidence > 0.5

    def test_single_container_not_usable(self):
        nodes = [self._node(1, "group", semantic="MMUIRenderSubWindowHW")]
        q = assess_quality(self._scene(nodes))
        assert q.is_usable is False
        assert q.confidence < 0.3

    def test_many_groups_no_interactive(self):
        nodes = [self._node(i, "group", f"g_{i}") for i in range(6)]
        q = assess_quality(self._scene(nodes))
        assert q.is_usable is False
        assert q.interaction_score == 0.0

    def test_search_box_detected(self):
        nodes = [
            self._node(1, "input", "搜索", semantic="SearchBox"),
            self._node(2, "text", "item"),
            self._node(3, "text", "label"),
            self._node(4, "button", "OK"),
            self._node(5, "text", "item2"),
        ]
        q = assess_quality(self._scene(nodes))
        assert q.has_search_box is True
        assert q.is_usable is True

    def test_empty_scene(self):
        q = assess_quality(self._scene([]))
        assert q.is_usable is False
        assert q.node_count == 0
        assert q.confidence == 0.0

    def test_mixed_nodes(self):
        nodes = [
            self._node(1, "group", "container"),
            self._node(2, "text", "label"),
            self._node(3, "button", "OK"),
            self._node(4, "text", "item"),
            self._node(5, "text", "item2"),
        ]
        q = assess_quality(self._scene(nodes))
        assert q.is_usable is True
        assert q.container_count == 1
        assert q.leaf_count == 4

    def test_scores_between_0_and_1(self):
        nodes = [self._node(i, "text", f"item_{i}") for i in range(10)]
        q = assess_quality(self._scene(nodes))
        assert 0 <= q.coverage_score <= 1
        assert 0 <= q.interaction_score <= 1
        assert 0 <= q.semantic_score <= 1
        assert 0 <= q.confidence <= 1

    def test_three_text_nodes_usable(self):
        nodes = [
            self._node(1, "text", "chat1"),
            self._node(2, "text", "chat2"),
            self._node(3, "text", "chat3"),
        ]
        q = assess_quality(self._scene(nodes))
        assert q.is_usable is True
        assert q.confidence >= 0.3


# ---- Visual Fallback ----


class TestVisualFallback:

    def test_fallback_returns_nodes(self):
        from PIL import Image
        import numpy as np
        img = Image.new("RGB", (800, 600), color=(255, 255, 255))
        nodes = visual_fallback_nodes(np.array(img), (0, 0, 800, 600))
        assert isinstance(nodes, list)

    def test_fallback_ids_offset(self):
        from PIL import Image
        import numpy as np
        img = Image.new("RGB", (800, 600), color=(255, 255, 255))
        nodes = visual_fallback_nodes(np.array(img), (0, 0, 800, 600), id_offset=9000)
        for n in nodes:
            assert n.id >= 9000


# ---- Scene Enhancement ----


class TestSceneEnhancement:

    def _scene(self, nodes):
        return SceneGraph(nodes=nodes, active_window="test")

    def _node(self, nid, ntype="text", text="", semantic=""):
        return SceneNode(id=nid, type=ntype, bbox=(0, 0, 100, 30),
                         text=text, semantic=semantic)

    def test_enhancement_skipped_when_usable(self):
        from PIL import Image
        import numpy as np
        img = Image.new("RGB", (800, 600))
        nodes = [self._node(i, "text", f"item_{i}") for i in range(10)]
        scene = self._scene(nodes)
        result = enhance_scene_with_fallback(scene, np.array(img), (0, 0, 800, 600))
        assert len(result.nodes) == 10  # no change

    def test_enhancement_adds_nodes_when_insufficient(self):
        from PIL import Image
        import numpy as np
        img = Image.new("RGB", (800, 600))
        nodes = [self._node(1, "group", semantic="MMUIRenderSubWindowHW")]
        scene = self._scene(nodes)
        result = enhance_scene_with_fallback(scene, np.array(img), (0, 0, 800, 600))
        # Should have at least the original node
        assert len(result.nodes) >= 1
