
> A desktop-grade web editor for Prolog-based knowledge graphs — with an
> interactive PyVis visualization, colored tables, Prolog syntax
> highlighting, natural-language import and a built-in PyAgentProlog
> query engine.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Screenshots](#screenshots)
- [Data format](#data-format)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Usage guide](#usage-guide)
  - [Project management](#project-management)
  - [Editor tabs](#editor-tabs)
  - [Visualization](#visualization)
  - [Queries](#queries)
- [Query examples](#query-examples)
- [Configuration](#configuration)
- [Project structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

**Knowledge Graph Editor** is a Gradio-based UI for designing, visualizing
and querying knowledge graphs stored as Prolog facts. It integrates three
ideas:

1. **A simple Prolog graph schema** — `node/3`, `edge/3`, `attribute/3` —
   that plays nicely with any Prolog engine (canonical form used by
   [`text_to_prolog`](https://github.com/) for natural-language conversion).
2. **Interactive visualization** — every edit shows up immediately in a
   PyVis graph with zoom, pan, hover tooltips and per-type coloring.
3. **A real Prolog query engine** — queries are executed by
   [**PyAgentProlog**](https://github.com/binom0x/pyagentprolog), so you can use `findall/3`,
   negation, arithmetic, meta-predicates — everything the engine supports.

The interface is dark, compact and designed for long editing sessions.

---

## Features

| Area | Highlights |
|---|---|
| **Editing** | CRUD on nodes (`id`, `type`), edges (`source`, `target`, `predicate`), attributes (`entity`, `name`, `value`). |
| **Tables** | Colored HTML tables with per-type chips, degrees, sticky headers. |
| **Prolog view** | Two-pane tab: syntax-highlighted preview + editable raw source with live re-highlight. |
| **Visualization** | Interactive PyVis graph: zoom, pan, physics, hover tooltips, per-type colors, size proportional to degree. |
| **Import** | `.pl` files, raw Prolog text, natural language (RU + EN). |
| **Export** | Save as `.pl`. Fully compatible with the graph schema used by `text_to_prolog`. |
| **Queries** | PyAgentProlog engine — `node/2,3`, `edge/2,3`, `attribute/3`, negation, arithmetic, `findall/3`, `bagof/3`, `setof/3`, `member/2`, etc. |
| **Theming** | Dark GitHub-inspired theme, forced regardless of OS preference. |
| **Diag** | One-click JSON diagnostics: node/edge counts, node types, predicates, availability of optional dependencies. |

---
## Data format

Every graph is stored as a small Prolog program:

```prolog
node(Id, Props, Type).
edge(Source, Target, Predicate).
attribute(Entity, Name, Value).
```

### Examples

```prolog
node(apple, [], org).
node(iphone, [], thing).
node(smartphone, [], concept).
node(elon_musk, [], person).
node(spacex, [], org).

edge(apple, iphone, releases).
edge(apple, smartphone, produces).
edge(elon_musk, spacex, owns).

attribute(iphone, release_year, '2022').
attribute(spacex, industry, 'aerospace').
```

### Field reference

| Field | Meaning | Constraints |
|---|---|---|
| `Id` | Unique identifier | Written **without quotes** if it is a valid Prolog atom (`[a-z][A-Za-z0-9_]*`), otherwise quoted (`'...'`). This matters: `node(apple, X)` will not match `node('apple', X)`. |
| `Props` | List of `key='value'` pairs | Empty list `[]` when none. |
| `Type` | Node type (atom) | Used for coloring in tables and PyVis. |
| `Source`, `Target` | Node ids | Created automatically if missing. |
| `Predicate` | Relation name | Atom. |
| `Name` | Attribute name | Atom. |
| `Value` | Attribute value | Always a string in `'...'`. |

### Convenience rules

The editor transparently appends these two rules to every query, so
`node/2` and `edge/2` work without explicit facts:

```prolog
node(Id, Type) :- node(Id, _, Type).
edge(S, T) :- edge(S, T, _).
```

### Node type colors

| Type | Color |
|---|---|
| `concept` | 🔵 `#58a6ff` |
| `person` | 🟢 `#7ee787` |
| `org` / `organization` | 🟠 `#f0883e` |
| `place` / `loc` | 🟣 `#d2a8ff` |
| `event` | 🔴 `#ff7b72` |
| `thing` | 💠 `#79c0ff` |
| `product` | 🟡 `#ffa657` |
| other | ⚪ `#8b949e` |

Add custom types by editing `_NODE_TYPE_COLORS` in `app.py` and
`_TYPE_COLORS` in `graph_layout.py`.

---

## Requirements

- **Python** ≥ 3.10
- **Gradio** 4.x, 5.x or 6.x
- **PyVis** ≥ 0.3 (for visualization)
- **PyAgentProlog** (`prolog` package) on `sys.path` — used for queries
- **tkinter** — bundled with Python on Windows/macOS, `sudo apt install python3-tk` on Linux

### Optional

- **`text_to_prolog.py`** — natural-language import
- **`pymorphy3`** — better Russian lemmatization
- **`spacy` + `en_core_web_sm`** — better English parsing
- **`spacy` + `ru_core_news_sm`** — Russian NER (proper noun merging)

---

## Installation

### From PyPI (when published)

```bash
pip install kg-editor
# full functionality:
pip install kg-editor[full]
pip install pyagentprolog  # query engine + NL-import
```

### From source (dev)

```bash
git clone https://github.com/binom0x/kg-editor.git
cd kg-editor
pip install -e .
# or with dev extras:
pip install -e ".[dev]"
```

### PyAgentProlog

The query engine and NL-import depend on **PyAgentProlog**
(the `prolog` package). It's not on PyPI yet, so install it from
source:

```bash
git clone https://github.com/binom0x/pyagentprolog.git
cd pyagentprolog
pip install -e .
```

Without PyAgentProlog, `kg-editor` still runs, but the query panel
shows a warning and NL-import is disabled.

### Verification

```bash
python -c "import kg_editor; print(kg_editor.__version__)"
python -c "from prolog.agent import Agent; print('PyAgentProlog OK')"
python -c "import pyvis; print('PyVis OK')"
```

## Quick start

```bash
kg-editor
```

Opens `http://127.0.0.1:7860`.

To expose on the LAN:

```bash
kg-editor --host 0.0.0.0 --port 8080
```

Or via Python API:

```python
from kg_editor import launch
launch(host="0.0.0.0", port=8080, share=False)
```

Quick sanity check:

```python
python -c "from prolog.agent import Agent; print('PyAgentProlog OK')"
python -c "import pyvis; print('PyVis OK')"
```

---

## Quick start

```bash
python app.py
```

The browser opens at `http://127.0.0.1:7860`.

To expose on the LAN:

```bash
python -c "from app import launch; launch(host='0.0.0.0', port=7860)"
```

To enable Gradio's public sharing link:

```bash
python -c "from app import launch; launch(share=True)"
```

### First run

1. Click **📚** (book icon) to load the demo graph.
2. The visualization on the right shows 5 nodes and 3 edges.
3. Type a query like `edge(X, Y, owns).` → **▶ Query**.
4. Result: `[{"X": "elon_musk", "Y": "spacex"}]`.

---

## Usage guide

The UI is organized in three columns:

```
┌────────────────┬────────────────────┬────────────────────┐
│ 📁 Graph/Prj   │ 🧩 Graph editor   │ 🖼️ Visualization   │
│                │                    │    (PyVis)         │
│  📂 🆕 💾 📚  |  [Nodes][Edges]   │                     │
│  Stats         │  [Attrs][Prolog]   │  🔎 Queries        │
│  NL import     │                    │                    │
│  Prolog import │                    │                    │
│  Diagnostics   │                    │                    │
└────────────────┴────────────────────┴────────────────────┘
```

### Project management

| Button        | Action                                                                |
| ------------- | --------------------------------------------------------------------- |
| **📂 Open**   | Load a `.pl` file from disk.                                          |
| **🆕 Create** | Create a new project folder with an empty `graph.pl`.                 |
| **💾 Save**   | Save the current graph to the current file, or open a Save-As dialog. |
| **📚**        | Load a built-in demo graph (apple / iphone / spacex).                 |

Below the buttons, the **stats line** shows counts of nodes, edges and
attributes — updated after every change.

### Editor tabs

#### Nodes

- Table columns: `id`, `type`, `degree`.
- **Add:** enter `id` and `type` → click **➕**.
- **Remove:** pick from the dropdown → click **🗑️**.
- Removing a node also removes all its edges and attributes.

#### Edges

- Table columns: `idx`, `source`, `predicate`, `target`.
- **Add:** fill all three fields → **➕**. Missing nodes are auto-created.
- **Remove:** pick from the dropdown → **🗑️**.

#### Attributes

- Table columns: `idx`, `entity`, `name`, `value`.
- **Add:** fill all three fields → **➕**.
- **Remove:** pick from the dropdown → **🗑️**.

#### Prolog source

- **Top:** syntax-highlighted read-only preview.
- **Bottom (accordion):** editable raw Prolog text — the preview updates live.
- **🔄 Refresh from graph** — regenerate the source from the current model.
- **📥 Apply from Prolog** — parse the text and **replace** the graph.

### Visualization

The right column hosts an interactive PyVis graph.

| Interaction | Result |
|---|---|
| Mouse wheel | Zoom around cursor |
| Drag background | Pan |
| Drag node | Move node (physics re-settles) |
| Hover node | Tooltip: `apple (org) — degree 2` |
| Hover edge | Tooltip: `apple —[releases]→ iphone` |
| Buttons `+` / `−` / `⟳` | Zoom in / out / reset |
| Navigation arrows | Pan in 4 directions |

Graph is rebuilt automatically on every edit. Rendering uses
`cdn_resources="remote"` so the iframe HTML stays small (~10 KB);
`vis-network` is fetched from jsDelivr. Change to `"local"` in
`graph_layout.py` for offline use (bigger HTML, fully self-contained).

### Queries

Queries are executed by **PyAgentProlog** — the full engine, not a subset.

- Every query runs on a **fresh** `Agent`, so side effects (`assertz`,
  `retract`) only last for the duration of one query.
- Trailing `.` is optional — it is added automatically.
- Result is JSON: a list of substitutions, or `{"result": true/false}`.

---

## Query examples

All examples below assume the demo graph is loaded.

### List everything

```prolog
node(Id, T).
```

### Filter by type

```prolog
node(Id, org).
```

### Traverse edges

```prolog
edge(X, Y, owns).
```

### Mixed filters

```prolog
attribute(iphone, release_year, Y).
```

### Negation

```prolog
node(X, T), \+ (T = person).
```

### Avoid self-loops

```prolog
edge(A, B, _), \+ (A = B).
```

### Collect all out-edges of a node

```prolog
findall(X, edge(apple, X, _), L).
```

### Two-hop reachability

```prolog
edge(apple, X, _), edge(X, Y, _).
```

### Complex — all owners of organizations

```prolog
node(A, person), node(B, org), edge(A, B, owns).
```

### Standard predicates available

`\+/1`, `=/2`, `\=/2`, `==/2`, `\==/2`, `>/2`, `</2`, `>=/2`, `=</2`,
`is/2`, `findall/3`, `bagof/3`, `setof/3`, `member/2`, `append/3`,
`length/2`, `atom/1`, `integer/1`, `compound/1`, `ground/1` and any
others exposed by PyAgentProlog.

---

## Configuration

### Theme and CSS

- **Theme:** `_make_theme()` in `app.py` returns a `gr.themes.Base` with
  the GitHub-dark palette. Change colors there.
- **Raw CSS:** `_GLOBAL_CSS` — additional styling for tables, code view,
  tabs, accordions, scrollbars.
- **Dark override:** `_DARK_FORCE_HEAD` — small JS that forces
  `<html class="dark">` regardless of OS setting.

### Visualization

Change `render_pyvis` signature defaults:

```python
def render_pyvis(graph,
                 height_ratio: str = "12/7",   # 16/9 for a taller graph
                 max_height: int = 700,
                 min_height: int = 400) -> str:
```

Change `_PYVIS_OPTIONS` in `graph_layout.py` for physics, layout,
arrows, fonts.

### Node type colors

- `_NODE_TYPE_COLORS` in `app.py` — chips in tables.
- `_TYPE_COLORS` in `graph_layout.py` — node circles.

Keep them in sync.

### Query engine

To disable the query engine (e.g. to ship without PyAgentProlog),
set `_AGENT_OK = False` at the top of `app.py` — the query panel will
show a friendly warning and the rest of the editor keeps working.

---

## Project structure

```
kg-editor/
├── app.py              # Gradio UI, handlers, theme, wiring
├── graph_model.py      # KnowledgeGraph model + Prolog (de)serialization
├── graph_layout.py     # PyVis rendering (primary) + SVG (fallback)
├── text_to_prolog.py   # optional: NL → Prolog
├── docs/
│   ├── screenshot.png
│   ├── editor.png
│   ├── prolog-view.png
│   └── query.png
├── README.md
└── LICENSE
```

### File responsibilities

| File | Role |
|---|---|
| `app.py` | Gradio `Blocks`, all event handlers (`h_add_node`, `h_query`, …), theming. |
| `graph_model.py` | `KnowledgeGraph` class: `add_node`, `add_edge`, `add_attribute`, `remove_*`, `to_prolog`, `from_prolog`. Handles quoted/unquoted atoms. |
| `graph_layout.py` | `render_pyvis()` (main), `render_svg()` (backup), `spring_layout()` (pure-Python force-directed used by SVG). |
| `text_to_prolog.py` | Optional module. `TextToProlog().convert(text, mode="graph")` → Prolog source. Used by **✨ Extract to graph**. |

### Extension points

- **New predicates in queries** — `_CONVENIENCE_RULES` in `app.py`.
- **New node types** — see *Configuration → Node type colors*.
- **Custom PyVis layout** — `_PYVIS_OPTIONS` and `render_pyvis` in
  `graph_layout.py`.
- **Alternative NL extractors** — replace `TextToProlog` in
  `h_import_nl`.
- **Bulk operations** — subclass `KnowledgeGraph`, override
  `add_node` / `add_edge`.

---

## Troubleshooting

### "PyVis not installed"

```bash
pip install pyvis
```

### "PyAgentProlog not loaded"

Ensure `prolog/` is on `sys.path`:

```python
import sys
sys.path.append("/path/to/pyagentprolog")
```

### "text_to_prolog.py not found"

Put `text_to_prolog.py` next to `app.py`. NL-import additionally needs
`pymorphy3` (RU) and/or `spacy` + `en_core_web_sm` (EN).

### "Graph is empty" in the visualization

This is normal when no nodes exist. Click **📚** to load the demo graph,
or add a node manually.

### "No solutions" for a query

- **Case matters:** `apple` ≠ `Apple`.
- **Types matter:** `'2022'` (string) ≠ `2022` (number).
- **Arity matters:** `node(apple, X)` matches facts written as `node(apple, _X, _Y)` via the convenience rule; `node(apple, X, Y)` won't match facts with a bare `node(apple, org)`.

### Visualization does not fill its container height

The iframe injection `_PYVIS_INJECT` sets `html, body, .card, .card-body,
#mynetwork` to `height:100%`. If you forked and modified
`graph_layout.py`, make sure that CSS block is preserved.

### "Gradio 6.0: theme / css / head must be passed to launch()"

Already handled — `app.py` detects the Gradio version and routes
`theme` / `css` / `head` to the correct place.

### Tkinter file dialogs don't open

On Linux, install Tk:

```bash
sudo apt install python3-tk
```

### `UserWarning: The parameters have been moved...`

Harmless — an artifact of Gradio's migration. Already handled by
`_LAUNCH_THEME` in `app.py`.

---

## Contributing

1. Fork the repo.
2. Create a branch: `git checkout -b feature/my-feature`.
3. Keep style consistent with the existing files — 4 spaces, type hints,
   `from __future__ import annotations`.
4. Make sure `python app.py` runs before submitting.
5. Open a pull request.

Bug reports are welcome — please include:

- Python version, Gradio version, OS,
- a **minimal** `graph.pl` reproducing the issue,
- the query text (if the problem is with queries),
- a screenshot of the visualization (if visual).

---

## See also

- [PyAgentProlog](https://github.com/) — the Prolog engine powering queries.
- [PyVis](https://pyvis.readthedocs.io/) — interactive network visualization.
- [Gradio](https://gradio.app/) — the UI framework.
- [vis-network](https://visjs.github.io/vis-network/docs/network/) — the
  underlying graph renderer.
