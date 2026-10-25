"""Concept graph loading, canonical names and app normalisation."""

from curio.skills import ConceptGraph


def test_bundled_graph_loads():
    graph = ConceptGraph.load()
    assert "layers" in graph.concepts
    assert graph.related("vlookup")["xlookup"] == 0.8
    assert graph.related("xlookup")["vlookup"] == 0.8  # undirected
    assert graph.related("keyframes")["timeline"] > 0
    assert graph.related("cell references")["formulas"] > 0


def test_app_names_and_aliases():
    graph = ConceptGraph.load()
    assert graph.app("Adobe Photoshop 2024") == "photoshop"
    assert graph.app("Microsoft Excel") == "excel"
    assert graph.app("figma") == "figma"
    assert graph.canonical("figma", "Frames") == "layers"
    assert graph.canonical("photoshop", "frames") == "frames"  # only figma calls them that
    assert graph.canonical("excel", "PivotTable") == "pivot tables"
    assert graph.canonical("excel", "something new") == "something new"
    assert graph.name_in("layers", "figma") == "frames"
    assert graph.name_in("layers", "photoshop") == "layers"
    assert graph.canonical_all("figma", ["frames", "layers", "", "Layer"]) == ("layers",)


def test_from_dict_ignores_self_edges_and_clamps():
    graph = ConceptGraph.from_dict(
        {"concepts": {"a": {}}, "related": [["a", "a", 1], ["a", "b", 3], ["b", "a", 0.2]]}
    )
    assert graph.related("a") == {"b": 1.0}
    assert graph.related("b") == {"a": 1.0}
    assert ConceptGraph.empty().related("a") == {}
