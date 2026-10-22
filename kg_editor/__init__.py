"""Knowledge Graph Editor.

A web editor for Prolog-based knowledge graphs, with:
  * PyVis interactive visualization;
  * colored HTML tables;
  * Prolog syntax highlighting;
  * optional NL-import (RU + EN);
  * PyAgentProlog-backed query engine.

Public API
----------
    from kg_editor import KnowledgeGraph, launch, build_ui, render_pyvis

CLI
---
    $ kg-editor                       # launch on 127.0.0.1:7860
    $ kg-editor --host 0.0.0.0 --port 8080
    $ python -m kg_editor             # equivalent
"""

from .graph_model import KnowledgeGraph, Node, Edge, Attribute
from .graph_layout import render_pyvis, render_svg
from .app import build_ui, launch

__version__ = "0.1.0"
__author__ = "Andrey Vorfolomeev"

__all__ = [
    "KnowledgeGraph", "Node", "Edge", "Attribute",
    "render_pyvis", "render_svg",
    "build_ui", "launch",
    "__version__",
]