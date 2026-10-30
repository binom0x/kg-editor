"""Shim + apply_facts_to_graph (живёт в kg_editor, потому что
зависит от kg_editor.KnowledgeGraph)."""
from nl2prolog.dialog import DialogTurn  # noqa: F401


def apply_facts_to_graph(graph, facts_src: str):
    """Добавить Prolog-факты к графу. graph — duck-typed:
    ожидаются add_node/add_edge/add_attribute."""
    if not facts_src or not facts_src.strip():
        return graph, {"nodes": 0, "edges": 0, "attributes": 0}

    try:
        from .graph_model import KnowledgeGraph
    except ImportError:
        from graph_model import KnowledgeGraph

    try:
        new_g = KnowledgeGraph.from_prolog(facts_src)
    except Exception as e:
        return graph, {"error": str(e)}

    try:
        for n in new_g.nodes.values():
            graph.add_node(n.id, n.type, n.props)
        for e in new_g.edges:
            graph.add_edge(e.source, e.target, e.predicate)
        for a in new_g.attributes:
            graph.add_attribute(a.entity, a.name, a.value)
    except Exception as e:
        return graph, {"error": str(e)}

    return graph, {
        "nodes": len(new_g.nodes),
        "edges": len(new_g.edges),
        "attributes": len(new_g.attributes),
    }


__all__ = ["DialogTurn", "apply_facts_to_graph"]