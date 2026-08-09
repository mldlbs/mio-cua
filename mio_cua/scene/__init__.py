"""Scene Graph: perception's core data structure.

Pipeline: OCR+UIA elements -> NodeBuilder -> RelationBuilder -> AffordanceBuilder,
plus optional layout regions (rapid_layout). Use ``build_scene`` to run the
whole thing in one call.
"""

from mio_cua.scene.graph import (
    Affordance,
    Region,
    Relation,
    SceneGraph,
    SceneNode,
)
from mio_cua.scene.builder import NodeBuilder
from mio_cua.scene.relations import RelationBuilder
from mio_cua.scene.affordances import AffordanceBuilder
from mio_cua.scene.diff import diff, display_text
from mio_cua.scene.regions import analyze as analyze_regions
from mio_cua.scene.memory import SceneMemory

__all__ = [
    "Affordance",
    "Region",
    "Relation",
    "SceneGraph",
    "SceneNode",
    "NodeBuilder",
    "RelationBuilder",
    "AffordanceBuilder",
    "SceneMemory",
    "build_scene",
    "analyze_regions",
    "diff",
    "display_text",
]


def build_scene(merged_elements, active_window="", regions=None, web_nodes=None) -> SceneGraph:
    """Build a full SceneGraph from the merged OCR+UIA element list.

    ``merged_elements`` must be the same list the InputController resolves
    element_ids against, so scene node ids == element ids.
    ``regions`` is an optional list of layout Regions (from rapid_layout).
    ``web_nodes`` is an optional list of OmniParser web-control nodes (their
    ids live above the element-id range).
    """
    nodes = NodeBuilder(merged_elements).build()
    if web_nodes:
        nodes = nodes + list(web_nodes)
    relations = RelationBuilder(nodes).build()
    affordances, display_ids = AffordanceBuilder(nodes, relations).build()
    return SceneGraph(
        nodes=nodes,
        relations=relations,
        affordances=affordances,
        display_ids=display_ids,
        regions=list(regions) if regions else [],
        active_window=active_window,
    )
