"""Smoke-тесты для KnowledgeGraph."""
from kg_editor import KnowledgeGraph


def test_add_and_remove_node():
    g = KnowledgeGraph()
    g.add_node("apple", "org")
    assert len(g.nodes) == 1
    assert g.nodes["apple"].type == "org"

    g.remove_node("apple")
    assert len(g.nodes) == 0


def test_add_edge_creates_missing_nodes():
    g = KnowledgeGraph()
    g.add_edge("apple", "iphone", "releases")
    assert "apple" in g.nodes
    assert "iphone" in g.nodes
    assert len(g.edges) == 1


def test_roundtrip_prolog():
    g = KnowledgeGraph()
    g.add_node("apple", "org")
    g.add_node("iphone", "thing")
    g.add_edge("apple", "iphone", "releases")
    g.add_attribute("iphone", "release_year", "2022")

    src = g.to_prolog()
    g2 = KnowledgeGraph.from_prolog(src)

    assert g2.summary() == g.summary()
    assert "apple" in g2.nodes
    assert g2.nodes["apple"].type == "org"
    assert any(e.predicate == "releases" for e in g2.edges)
    assert any(a.value == "2022" for a in g2.attributes)


def test_quoted_atoms_preserved():
    g = KnowledgeGraph()
    g.add_node("илон_маск", "person")
    src = g.to_prolog()
    assert "'илон_маск'" in src  # кириллица → в кавычках

    g2 = KnowledgeGraph.from_prolog(src)
    assert "илон_маск" in g2.nodes