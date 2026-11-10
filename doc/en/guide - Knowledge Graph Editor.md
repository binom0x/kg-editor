# KnowledgeGraph Editor — User Guide

**v5.14**

## Table of Contents

1. [Installation and Launch](#1-installation-and-launch)
2. [Interface Overview](#2-interface-overview)
3. [Working with a Project](#3-working-with-a-project)
4. [NL Import: Three Modes](#4-nl-import-three-modes)
5. [Graph Editor](#5-graph-editor)
6. [Visualization](#6-visualization)
7. [Queries](#7-queries)
8. [Dialog Mode](#8-dialog-mode)
9. [File Format](#9-file-format)
10. [Common Issues](#10-common-issues)
11. [Architecture](#11-architecture)
12. [Migration](#12-migration)

---

## What's New in v5.14

- **Graph merging** — the **"🔀 Merge"** button in the project row. Appends the graph from a `.pl` file to the current one **additively** (only adds what's missing, without overwriting existing data).
- **Project status** moved to a separate box under the statistics — messages about loading/creating/saving/merging are visible immediately, without expanding an accordion.
- **Dialog is not reset on merge** — the operation is additive, so a pending question remains meaningful.
- **`skipped` counters** in the merge status — shows how many nodes/edges/attributes already existed in the graph or were filtered out as service words.

**Inherited from v5.13:** dialog mode in the UI, transcript with `solutions`, PyVis freeze, port 7861, possessive frames, `_apply_facts_local`, extended diagnostics.

---

## 1. Installation and Launch

### 1.1. Requirements

| Component | Required | Purpose |
|---|---|---|
| **Python** 3.10+ | ✅ | Runtime |
| **Gradio** 4.x / 5.x / 6.x | ✅ | UI |
| **PyVis** ≥ 0.3 | ⭐ strongly recommended | Visualization (stub without it) |
| **PyAgentProlog** (`prolog`) | ⭐ strongly recommended | Queries (query panel disabled without it) |
| **tkinter** | ⭐ | Native file dialogs |
| **`nl2prolog`** | ⭕ optional | NL import + dialog (or your own extractor) |
| **PyPDF2 / python-docx** | ⭕ | Reading PDF/DOCX |

**Important:** `nl2prolog` is **not a dependency** but the **default extractor**. Without it, the editor works fully: opening/saving/merging `.pl`, editing nodes/edges/attributes, importing Prolog code, queries, visualization. Only NL import and dialog mode won't work.

### 1.2. Installing Dependencies

```bash
# Base (required)
pip install gradio pyvis

# NL import + dialog — option A: nl2prolog package (recommended)
pip install "nl2prolog[ru,prolog]"

# NL import — option B: only for your own converter — install nothing
# (load your .py in the UI, see §4.4). Dialog is unavailable in this case.

# PyAgentProlog (if you need queries)
pip install -e /path/to/pyagentprolog

# Optional: reading PDF/DOCX
pip install PyPDF2 python-docx
```

### 1.3. Launch

```bash
kg-editor
```

Opens a browser at `http://127.0.0.1:7861`.

**CLI parameters:**

```bash
kg-editor --host 0.0.0.0 --port 8080   # Access from other machines
kg-editor --share                      # Public gradio.live link
kg-editor --no-browser                 # Don't open browser
```

**Python API:**

```python
from kg_editor import launch
launch(host="0.0.0.0", port=8080)
```

### 1.4. Verifying State After Launch

On startup, `app.py` determines four flags:
- `_T2P_OK` — whether `text_to_prolog` works (built-in or shim).
- `_NL2PROLOG_OK` — whether the `nl2prolog` package is installed.
- `_AGENT_OK` — whether `PyAgentProlog` is available.
- `_DIALOG_OK` — whether `DialogTurn` from `nl2prolog` is available.

The result is visible in:
- The **banner** in the "📝 Import from NL" accordion.
- The **diagnostics** ("🔬 Diagnostics" accordion → "🔄 Show").
- The **"💬 Dialog" tab** — if `_DIALOG_OK == False`, a banner is shown instead of controls.

---

## 2. Interface Overview

Three columns + modal windows.

```
┌────────────────────┬──────────────────────┬────────────────────┐
│ 📁 Graph / Project │ 🧩 Graph Editor      │ 🖼️ Visualization   │
│  📂 🔀 🆕 💾 📚    │  [Nodes][Edges]      │  (PyVis)           │
│  Statistics        │  [Attributes]        │                    │
│  Project status    │  [🛡️ Filtered]       │  🔎 Queries        │
│                    │  [💬 Dialog]         │                    │
│  📝 Import from NL │  [Prolog source]     │                    │
│  ⚙️ Converter      │                      │                    │
│  📥 Import Prolog  │                      │                    │
│  🔬 Diagnostics    │                      │                    │
└────────────────────┴──────────────────────┴────────────────────┘
```

**Data format** (compatible with `nl2prolog._to_graph_program`):

```prolog
node(Id, Props, Type).           % node: id, properties, type
edge(Source, Target, Predicate). % edge
attribute(Entity, Name, Value).  % attribute
```

When executing queries, the following rules are automatically added on top of the facts:

```prolog
node(Id, Type) :- node(Id, _, Type).
edge(S, T) :- edge(S, T, _).
```

---

## 3. Working with a Project

### 3.1. 📂 Open
Load a `.pl` file from disk. **Replaces** the current graph. **Resets the active dialog** (a pending question loses meaning for the new graph).

### 3.2. 🔀 Merge — **new in v5.14**

Load a `.pl` file and **append** its contents to the current graph. The current graph is not replaced — it is **augmented**.

**Where:** the `🔀 Merge` button in the project row, between `📂 Open` and `🆕 Create`.

**What happens:**

1. A native dialog opens for selecting a `.pl` file.
2. The file is parsed into a separate `KnowledgeGraph`.
3. Elements are transferred **additively** into the current graph.
4. The result is visible in two places:
   - **Project status** (box under the statistics) — detailed report.
   - **Counters** (Nodes/Edges/Attributes) — updated automatically.
5. The **"Prolog source"** tab is rebuilt from the merged graph.

**Merge semantics** (policy "current graph wins"):

| Element | Behavior |
|---|---|
| **Nodes** | Only missing ones are added. If `apple` already exists with type `org`, and in the file it has type `concept`, the type is **not overwritten** (stays `org`). The `props` of existing nodes are also unchanged. |
| **Edges** | Deduplicated by `(source, target, predicate)`. Matches are not duplicated. |
| **Attributes** | Deduplicated by `(entity, name, value)`. If `(entity, name)` matches but `value` differs — these are different facts, both are kept. |
| **Service words** | Atoms dropped by the filter (`очень`, `наименование`, OCR artifacts) are not added. Counted as `skipped`. |
| **Order** | Existing elements stay in place; new ones are appended at the end (insertion order preserved). |

**Status message formats:**

Success with additions:
```
✓ Merged: /path/to/file.pl
  +5 nodes, +7 edges, +2 attributes
  skipped (already present or invalid): 3 nodes, 1 edges, 0 attributes
```

Full match:
```
ℹ️ Nothing to add: /path/to/file.pl
  Everything is already in the graph (10 elements skipped).
```

Empty file:
```
ℹ️ File is empty: /path/to/file.pl
```

Parse/merge error:
```
✗ Merge error: <exception text>
```
On error, the graph is **not modified** — the operation is atomic per element.

**What does NOT happen during merge:**

- The graph is not replaced — use `📂 Open` if you need a replacement.
- The type and `props` of existing nodes are not overwritten — this is the intentional "current graph wins" policy.
- `dlg_state` is **not reset** — this is an augmentation, not a replacement. If a pending question was set, it remains valid. If you want to start the dialog over — press `🗑️` on the "💬 Dialog" tab.

**Typical scenarios:**

| Task | Action |
|---|---|
| Combine one graph from several `.pl` files | Open the base → `🔀 Merge` for each additional one |
| Add facts from another source to the current project | `🔀 Merge` |
| Replace the graph entirely | `📂 Open` (not merge) |
| Check what a file adds | `🔀 Merge` → look at `+N` in the status |

### 3.3. 🆕 Create
Create a project folder with a `graph.pl` template. **Replaces** the current graph. Resets the dialog.

### 3.4. 💾 Save
Save to an existing file or open "Save as…".

### 3.5. 📚 Demo Graph
Load `apple` / `iphone` / `spacex` / `elon_musk` with attributes and types. **Replaces** the current graph. Resets the dialog.

### 3.6. Statistics
Counters for nodes / edges / attributes. Updated automatically after every change (including NL import, merge, queries with mutations, and dialog turns).

### 3.7. 📥 Import from Prolog
Paste Prolog facts → **📥 Parse**. The current graph is **replaced**. If you need additive mode — save the pasted code to a `.pl` file and use `🔀 Merge`.

### 3.8. 🔬 Diagnostics

JSON snapshot of the current state (v5.14):

```json
{
  "summary": {"nodes": 42, "edges": 55, "attributes": 7},
  "pyagent": true,
  "t2p_ok": true,
  "nl2prolog_ok": true,
  "nl2prolog_version": "1.0.2",
  "t2p_custom": false,
  "dialog_ok": true,
  "dialog_active": false,
  "dialog_pending": false
}
```

| Field | Meaning |
|---|---|
| `pyagent` | whether `prolog.agent.Agent` is available |
| `t2p_ok` | whether `text_to_prolog` works (built-in or shim) |
| `nl2prolog_ok` | whether the `nl2prolog` package is installed |
| `nl2prolog_version` | package version (or `null`) |
| `t2p_custom` | whether a custom `.py` is loaded via the UI |
| `dialog_ok` | whether `DialogTurn` works (requires `nl2prolog`) |
| `dialog_active` | whether `DialogTurn` is initialized in the current session |
| `dialog_pending` | whether there is a pending question in the dialog |

---

## 4. NL Import: Three Modes

The **"📝 Import from NL"** accordion in Column 1. Inside — a **status banner** that immediately tells you what's working.

### 4.1. Banner — 5 Possible States

| State | What you see | What to do |
|---|---|---|
| ✅ **`nl2prolog` installed** | "✅ nl2prolog 1.0.2 — default extractor" | Nothing. Works out of the box. |
| ✅ **Built-in `text_to_prolog`** | "✅ Built-in text_to_prolog loaded (nl2prolog package not found)" | Works via a local module (non-standard build). |
| ✅ **Custom extractor** | "✅ Custom extractor connected" | A `.py` was loaded via the UI. |
| ⚠️ **Broken shim** | "⚠️ nl2prolog X installed, but text_to_prolog shim fails to load" | Check the package installation, or load your own `.py`. |
| ℹ️ **No extractor** | "ℹ️ NL extractor not set. NL import unavailable" + instructions | Load your own `.py` (the "⚙️ Converter" accordion is already expanded) or install `pip install "nl2prolog[ru]"` |

### 4.2. Loading Text

- **Manual input:** the "Brief text" field.
- **File:** drag and drop `.txt`, `.pdf`, `.docx`, or `.fb2` into the upload zone. A status *"✅ File loaded (N characters)"* appears, along with a **📝 Open text** button that opens a modal for viewing/editing the full text. After edits — **✅ Apply** or **❌ Cancel**.

### 4.3. Two Independent Buttons

| Button | What it does | Graph | "Queries" field |
|---|---|---|---|
| **📊 Facts** (primary) | `parse(text, strict=True, facts_from_questions=True)` | augmented | untouched |
| **❓ Query** | `parse(text, strict=True, facts_from_questions=False)` | untouched | filled |
| **🗑️** | Clear the entered text and state | — | — |

- **📊 Facts** — KB building mode: extracts `node/3`, `edge/3`, `attribute/3` from **all** sentences (including questions).
- **❓ Query** — Q&A mode: turns the question into a Prolog query without polluting the graph with facts from the question.

**If no extractor is set** — both buttons return a hint:

```
ℹ️ NL extractor not set.
The graph editor works fully — you can open/save .pl,
edit nodes/edges/attributes, import Prolog code,
build queries.
For NL import you need to:
  → Load your own .py module with a TextToProlog class
  → Or install the built-in one: pip install "nl2prolog[ru]"
```

### 4.4. ⚙️ Custom Converter

The **"⚙️ Custom converter"** accordion inside the NL accordion.

**Automatically expanded** if the built-in extractor is unavailable (`_T2P_OK == False`).

Buttons:
- **📂 Select** — choose a `.py` file.
- **✅ Load** — import the module. A `TextToProlog` class with a `parse()` **or** `convert()` method is required.
- **↺ Built-in** — revert to the built-in `text_to_prolog.py` (or to `nl2prolog` if the package is installed).

**Loading/resetting the converter resets the active dialog** — `dlg_state = None`. This is correct: a custom extractor doesn't provide `DialogTurn`, so the old dialog would be meaningless with the new extractor.

After a successful load:
- The banner changes to "✅ Custom extractor connected".
- The **📊 Facts** / **❓ Query** buttons use your class.
- The "💬 Dialog" tab shows "⚠️ Dialog mode unavailable" (a custom `.py` doesn't provide `DialogTurn`).

**Requirements for a custom `.py`:**

```python
class TextToProlog:
    def __init__(self, **kwargs): ...
    def parse(self, text, **kwargs) -> tuple[str, str]: ...
    # or
    def convert(self, text, mode="graph", **kwargs) -> str: ...
```

Optionally — a `filtered_atoms` attribute if you want to support the "🛡️ Log filtered" checkbox.

### 4.5. 🛡️ Log Filtered

A checkbox in the NL accordion (enabled by default).

When enabled, `parse(..., log_filtered=True)` fills `t2p.filtered_atoms` — a list of `(term_desc, reason)` pairs for all terms removed at the `_dedup` and `_postfilter_generic` stages.

The result appears on the **🛡️ Filtered** tab (Column 2).

**Typical reasons:**

| Reason | Meaning |
|---|---|
| `generic_adj: очень` | service adjective |
| `compound_ner_blacklisted: наименование_технопарка` | NER false-positive |
| `noise_atom: ст` | OCR artifact |
| `attr_label node: срок` | noun from `ATTR_LABEL_NOUNS` |
| `attr_label invert: наименование → должность` | reclassified as `attribute(должность, наименование, true)` |
| `postfilter attr value noise: следующий` | Rel-adjective in an attribute value |

When the checkbox is **disabled**, overhead is zero.

---

## 5. Graph Editor

### 5.1. "Nodes" Tab

Table **id / type / degree** (degree = number of incident edges).

- **Add:** `id`, `type` → **➕**.
- **Edit:** click a row → fields are populated → **💾**.
- **Delete:** click → **🗑️** (also deletes all edges and attributes of the node).

**Safe ID editing:**
- If the new ID already exists → "✗ Node '…' already exists", data is not lost.
- If the new ID is invalid → "✗ Rename error: …", graph is untouched.
- **Compound IDs are allowed:** `российская_федерация`, `northern_ireland`, `тихий_океан`.
- **Single service words** (`очень`, `этот`, `и`) are rejected.

**Type palette:**

| Type | Color |
|---|---|
| `concept` | 🔵 light blue |
| `person` | 🟢 green |
| `org` / `organization` | 🟠 orange |
| `place` / `loc` | 🟣 purple |
| `event` | 🔴 red |
| `thing` | 💠 pale blue |
| `product` | 🟡 yellow-orange |
| `default` | ⚪ gray |

### 5.2. "Edges" Tab

Table **idx / source / predicate / target** (source and target are colored chips by node type).

- **Add:** `source`, `target`, `predicate` → **➕** (if source/target aren't in the graph — they're created).
- **Edit:** click → fields populated → **💾**.
- **Delete:** click → **🗑️**.

**Safe editing:** if source/target is invalid during editing, the old version of the edge is not lost, and an error is shown.

### 5.3. "Attributes" Tab

Table **idx / entity / name / value**.

- **Add:** `entity`, `name`, `value` → **➕** (entity is created if absent).
- **Delete:** select from the dropdown → **🗑️**.

### 5.4. "🛡️ Filtered" Tab

Table **term / atom** and **filter reason** — what was removed during NL import with the checkbox enabled.

If logging is off or nothing was filtered — the placeholder *"Nothing filtered (or logging disabled). Enable the checkbox in the NL import block."*

### 5.5. "💬 Dialog" Tab

See §8.

### 5.6. "Prolog source" Tab

- **At the top** — read-only view with Prolog syntax highlighting.
- **In the "✏️ Edit" accordion** — a field for manual editing.
- **🔄 Refresh from graph** — rebuild the text from the model.
- **📥 Apply** — replace the graph with the text from the field.

**After `🔀 Merge`**, the tab updates automatically — showing the merged graph.

---

## 6. Visualization

Interactive PyVis graph, GitHub-dark theme.

- **Nodes** — size based on degree (`√`-normalization, min 16px, max 40px).
- **Edges** — thickness 2.5, light gray `#8b949e`, blue on hover.
- **Hover** — tooltips for nodes/edges.

| Action | Result |
|---|---|
| Mouse wheel | Zoom |
| Drag background | Pan |
| Drag node | Move (node **stays** in the new position) |
| `+`/`−`/`⟳` buttons | Zoom / reset |
| **`⛶` (top left)** | **Expand to fullscreen** |
| `✕` (in fullscreen) | Collapse |
| `Esc` | Exit fullscreen |

**Physics (v5.13+):** after loading the graph, a nice stabilization runs (~300 iterations), then **physics is automatically disabled**. This eliminates the "jitter" and "rotation" that existed in v5.12 due to:

- `physics.enabled: true` without freezing after stabilization;
- `edges.smooth.type: "dynamic"` — recomputing curvature every frame;
- `barnesHut.avoidOverlap: 0.5` — a source of oscillation.

If the graph is "stuck" in an awkward configuration — drag nodes manually (they stay in place) or recreate the graph (switching tabs doesn't recompute physics).

**After `🔀 Merge`**, the visualization is rebuilt for the merged graph (via `_refresh`).

**If PyVis is not installed** — a stub with a `pip install pyvis` hint is shown instead of the graph.

---

## 7. Queries

The engine is **PyAgentProlog** (`prolog.agent.Agent`). Queries are executed on a "fresh" agent — mutations (`assertz`, `retract`) don't affect the model.

### 7.1. Syntax

Enter a query (the period can be omitted) → **▶ Query**. Limit — 1000 solutions.

### 7.2. Available Predicates

Convenience rules are added automatically:

```prolog
node(Id, Type) :- node(Id, _, Type).
edge(S, T) :- edge(S, T, _).
```

Available: `node/2`, `node/3`, `edge/2`, `edge/3`, `attribute/3`, `\+`, `=`, `\=`, `is`, `findall/3`, `member/2`, `append/3`, and other standard ones.

### 7.3. Examples

| Query | What it returns |
|---|---|
| `node(apple, T).` | the type of node apple |
| `edge(X, Y, owns).` | who owns what |
| `edge(A, B, _), \+ (A = B).` | all edges without self-loops |
| `findall(X, edge(apple, X, _), L).` | all targets of apple's edges |
| `node(A, person), node(B, org), edge(A, B, owns).` | person → organization |

### 7.4. Result

A JSON array of solutions (`[{"X": "elon_musk", "Y": "spacex"}]`) or `{"result": true}` for ground queries.

### 7.5. If PyAgentProlog Is Not Installed

The query panel shows "⚠️ PyAgentProlog not loaded". The editor, visualization, merge, and dialog continue to work (the dialog will return "No solutions" for every question, since `Agent` isn't called).

---

## 8. Dialog Mode

**Full UI** — the **"💬 Dialog"** tab in Column 2.

### 8.1. What It Does

- **Asks a question** → tries to find an answer in the graph via `Agent`.
- **Enters a statement** → extracts facts and **adds them to the graph** automatically.
- **Clarifies** the answer via `✅ Yes` / `❌ No` on a pending question.
- Maintains a **transcript** of all turns.

### 8.2. Controls

| Element | Action |
|---|---|
| **▶ Ask** (primary) | NL question or statement → `DialogTurn.ask()` |
| **💬 Answer** | NL answer to a pending question → `DialogTurn.answer()` |
| **✅** | Answer "yes" to a pending question |
| **❌** | Answer "no" to a pending question |
| **🗑️** | Reset dialog: clear pending, keep history |
| **📜 Transcript** | read-only field with turn history |
| **⏳ Pending question** | Panel at the top — what's awaiting an answer |

### 8.3. Scenarios

**Scenario A — question with an answer:**

1. Graph:
   ```prolog
   node('регулятор', [], org).
   edge('регулятор', 'лицензия', 'выдавать').
   ```
2. Enter: `Кто выдает лицензию?` → **▶ Ask**.
3. Result:
   - `dlg_result`: `{"solutions": [{"X": "регулятор"}], "query": "edge(X, 'лицензия', 'выдавать')"}`
   - Status: `✓ 1 solution(s)`
   - Transcript: `[02] system/answer ✓ 1 solution(s): X=регулятор`
   - **Pending cleared automatically** (a correct answer doesn't require clarification).

**Scenario B — question without an answer:**

1. Graph is empty.
2. Enter: `У пользователя есть лицензия?` → **▶ Ask**.
3. Result:
   - `dlg_result`: `{"result": None, "query": "edge('пользователь', 'лицензия', 'иметь')"}`
   - Status: `No solutions` + `💡 No solution found. Press ✅ Yes / ❌ No`
   - Pending **is set** — "⏳ Pending question: У пользователя есть лицензия?"

**Scenario C — clarification:**

1. Continuation of scenario B.
2. Press **✅** — `DialogTurn.answer("да")` → `convert_answer` generates `true_condition(edge('пользователь', 'лицензия', 'иметь'))`.
3. The fact `true_condition/1` is **not added** to the graph (it's not `node/edge/attribute`), but pending is cleared.
4. Transcript: `[03] user/answer «да» facts (1): true_condition(...)`.

**Scenario D — statement:**

1. Enter: `Илон Маск владеет Tesla` → **▶ Ask**.
2. The NL parser returns `is_question: false` + `facts_extracted` with `node('илон_маск', _, person).` and `node('tesla', _, concept).`.
3. Facts are **added to the graph** automatically (see §8.5).
4. Transcript: `[04] user/question «Илон Маск владеет Tesla» facts (2): …`

**Scenario E — merge during a dialog (v5.14):**

1. Press `🔀 Merge` → append a file with facts.
2. **Dialog is not reset** — the pending question remains valid.
3. If the appended file contains an answer to the pending question — press `▶ Ask` again (with the same or a new text), `DialogTurn.ask` will recompute solutions on the updated graph.
4. If you need a clean dialog — `🗑️` on the "💬 Dialog" tab.

### 8.4. Transcript

Printed from `DialogTurn.transcript()` (in `nl2prolog`). Format:

```
[01] user/question
     «Кто выдает лицензию?»
     Q: edge(X, 'лицензия', 'выдавать')

[02] system/answer
     Q: edge(X, 'лицензия', 'выдавать')
     ✓ 1 solution(s):
         X=регулятор
```

If the latest transcript version (with `solutions`) isn't set in `DialogTurn` — update `nl2prolog` to v1.0.2+.

### 8.5. Applying Facts to the Graph

Statement → facts → graph is done via **`_apply_facts_local`** (in `app.py`):

- Builds `KnowledgeGraph.from_prolog(facts_src)`.
- Transfers nodes/edges/attributes into the current graph.
- Returns `{nodes, edges, attributes}` or `{error}`.
- **Does not use** `nl2prolog.dialog.apply_facts_to_graph` — that one tries to import `KnowledgeGraph` from its own package and fails with `'NoneType' object has no attribute 'from_prolog'`.

`true_condition/1`, `false_condition/1`, `user_condition/1` — are not mapped to `node/edge/attribute`, so they don't end up in the graph (this is expected).

### 8.6. Resetting the Dialog

- **🗑️** — `DialogTurn.reset()`: clears `pending_query`, `pending_facts`, `pending_question_text`. History is preserved.
- **Changing the extractor** (📂 / ✅ / ↺ in "⚙️ Converter") — `dlg_state = None`.
- **Replacing the graph** (📂 Open / 🆕 Create / 📚 Demo) — `dlg_state = None`.
- **Merge** (🔀 Merge) — `dlg_state` is **not reset**: the operation is additive, pending remains meaningful.

### 8.7. If `nl2prolog` Is Not Installed

The "💬 Dialog" tab shows an **orange banner**:

> ⚠️ Dialog mode unavailable.
> The dialog module doesn't load — the nl2prolog package is required.
> → Install: `pip install "nl2prolog[ru]"`
> → A custom .py extractor is insufficient for dialog.

The controls (▶, 💬, ✅, ❌, 🗑️) are **hidden**.

### 8.8. Fallback: Question Not Recognized

If the text ends with `?` but `parse()` returned an empty `query` — the status contains:

```
⚠️ Question not recognized by the parser (NL extractor returned an empty query).
Only facts were extracted from the text.
💡 Try rephrasing the question.
```

This is a signal to update `nl2prolog` (v5.11.17+ recognizes more constructions) or rephrase.

---

## 9. File Format

```prolog
node(apple, [], org).
node(spacex, [], org).
node(российская_федерация, [], place).    % compound ID without quotes
edge(apple, iphone, releases).
edge(elon_musk, spacex, owns).
attribute(iphone, release_year, '2022').
```

- **IDs / types / predicates** — without quotes if a valid atom (`[a-z][A-Za-z0-9_]*`), otherwise `'...'`.
- **Compound IDs** (`российская_федерация`) — valid atoms, go without quotes.
- **Attribute values** — always strings in `'...'`.

The file for `🔀 Merge` uses the same format. You can use the output of `💾 Save` from another project.

---

## 10. Common Issues

### 10.1. Editor Won't Start: `ImportError: cannot import name 'DialogTurn'`

**Cause:** an old version of `app.py` (pre-v5.12) is installed.

**Solution:** update `app.py` to v5.12+. The `dialog.py` import is now fully optional.

### 10.2. Banner: "ℹ️ NL extractor not set"

NL import and dialog are unavailable. Options:
- Install: `pip install "nl2prolog[ru]"`.
- Load your own `.py` in the "⚙️ Custom converter" section (it's already expanded). Dialog will remain unavailable.

### 10.3. Banner: "⚠️ nl2prolog X installed, but shim fails to load"

**Cause:** the `nl2prolog` package is installed, but `kg_editor.text_to_prolog` can't import it.

**Solution:**
1. Check: `python -c "import nl2prolog; print(nl2prolog.__version__)"`.
2. Reinstall: `pip install --force-reinstall "nl2prolog[ru]"`.
3. Or load your own `.py` via the converter.

### 10.4. "✗ Node '…' — service word"

Most likely you're trying to add a single adjective / pronoun / preposition.

**Compound IDs are allowed** (`российская_федерация`, `тихий_океан`).

### 10.5. "No solutions" in a Query

- Check case: `apple` ≠ `Apple`.
- Strings `'2022'` and numbers `2022` are different.
- Check the predicate: `edge('регулятор', 'лицензия', 'выдает')` in the KB vs. query `edge(X, 'лицензия', 'выдавать')` — they won't match (`выдает` ≠ `выдавать`). Use the lemmatized form.

### 10.6. Dialog: "No solutions" + false "Solution not found"

If `solutions` contains data but the status shows "Solution not found" — update `app.py` to v5.13.0. In earlier versions, `_dialog_hint_for_no_solution` falsely triggered (it checked `.get("result") is None`, which is true even for a missing key).

### 10.7. Dialog: `'NoneType' object has no attribute 'from_prolog'`

**Cause:** facts from a statement were being applied via `nl2prolog.dialog.apply_facts_to_graph`, which is broken.

**Solution:** update `app.py` to v5.13.0 — there `_apply_facts_local` uses `kg_editor.KnowledgeGraph`.

### 10.8. PyVis "jitters" / "rotates"

**Cause:** physics isn't frozen after stabilization (v5.12 and earlier).

**Solution:** update `graph_layout.py` to v5.13.0 — there `_PYVIS_FREEZE_JS` disables physics on the `stabilizationIterationsDone` event and via a 2.5 sec timeout.

### 10.9. Double Borders on Input Fields

**Cause:** `.block` from the Gradio theme + `border` from `.compact-tb input` — two outlines.

**Solution:** update the CSS to v5.12.1+ — `.compact-tb.block { border: none }` + a single outline on `<input>`.

### 10.10. Empty "🛡️ Filtered" Tab

- Is the **🛡️ Log filtered** checkbox enabled?
- Haven't you pressed import after disabling it?

### 10.11. Question Yields `edge('кто', …)` Instead of `edge(X, …)`

Update `nl2prolog` to **≥ 1.0.0**. Check: diagnostics should show `nl2prolog_ok: true`, `nl2prolog_version: "1.0.x"`.

### 10.12. Failed to Read PDF/DOCX

```bash
pip install PyPDF2 python-docx
```

### 10.13. `🔀 Merge` → "ℹ️ Nothing to add"

**Cause:** all elements from the file are already in the graph (per the dedup policy). This is not an error — the graph didn't change because it already contained everything needed.

**What to check:** the `skipped` counters in the status. If they're large — the file contents really do duplicate the current graph.

### 10.14. `🔀 Merge` → Node Type Not Updated

**Cause:** the merge policy — "current graph wins". Existing nodes are not overwritten in either type or `props`.

**Solution:** if you need to replace the type — edit the node manually on the "Nodes" tab (click → Type → 💾) or use `📂 Open` if you're ready to replace the graph entirely.

### 10.15. `🔀 Merge` → Some Elements Disappeared

**Cause:** atoms dropped by `generic_filter` (service words, OCR artifacts, NER false-positives) are not added during merge. They're accounted for in the `skipped` counters of the status.

**What to do:**
- If it's expected (service words) — nothing.
- If it's a real term dropped by the filter — add the node manually ("Nodes" tab).
- If the term should always be preserved — configure `generic_filter` in `graph_model.py` (see §11.2).

### 10.16. After `🔀 Merge` the Dialog Behaves Oddly

**Cause:** merge doesn't reset `dlg_state`, but the graph changed — the pending question may have become irrelevant (e.g., the answer appeared, or vice versa).

**Solution:**
- Press `▶ Ask` again — `DialogTurn.ask` will recompute solutions on the updated graph.
- Or `🗑️` on the "💬 Dialog" tab to reset pending and start over.

---

## 11. Architecture

### 11.1. Files

| File | Role | Version |
|---|---|---|
| `app.py` | UI, handlers, theme, wiring, dialog mode, merge | **v5.14** |
| `graph_model.py` | `KnowledgeGraph`, CRUD, (de)serialization, `merge`/`merge_from_prolog` | **v5.13** |
| `graph_layout.py` | `render_pyvis()`, `render_svg()` (backup), freeze-JS | **v5.13** |
| `text_to_prolog.py` | **shim** → `nl2prolog` | shim |
| `dialog.py` | **shim** → `nl2prolog.dialog` + local `apply_facts_to_graph` | shim |
| **`nl2prolog`** *(separate package)* | NL parser + dialog | **v1.0.x** |
| `noise.py` | POS-noise (if without `nl2prolog`) | — |
| `metrics.py`, `runner.py` | Offline evaluation | — |

### 11.2. Extension Points

**In `app.py`:**
- `_NODE_TYPE_COLORS` — type palette.
- `_CONVENIENCE_RULES` — rules for queries.
- `_nl_package_status_html()` — extractor status banner.
- `_dialog_unavailable_banner()` — dialog unavailability banner.
- `_apply_facts_local()` — applying Prolog facts to the graph.
- `h_merge_file()` — merge handler (v5.14).

**In `graph_layout.py`:**
- `_TYPE_COLORS` — PyVis palette.
- `_PYVIS_OPTIONS` — physics (stabilization with freeze), edges (`continuous`), nodes.
- `_PYVIS_FREEZE_JS` — JS hook that freezes physics after `stabilizationIterationsDone`.

**In `graph_model.py`:**
- `generic_filter=` — custom filter for service words.
- **`merge(other)`** — additive merge of another `KnowledgeGraph` into the current one (v5.13+).
- **`merge_from_prolog(text)`** — wrapper over `merge(from_prolog(text))` (v5.13+).

`merge` policy (for reference): nodes — only missing ones, type/props not overwritten; edges — dedup by `(source, target, predicate)`; attributes — dedup by `(entity, name, value)`. Returns statistics `{added_*, skipped_*}`.

**In `nl2prolog` (`TextToProlog` class attributes):**

| List | Purpose |
|---|---|
| `NER_ORG_BLACKLIST` | abstract nouns → `concept` |
| `ATTR_LABEL_NOUNS` | attribute labels → `attribute/3` |
| `ATTR_ADJ_WHITELIST` | Rel-adjectives that are **preserved** |
| `SHORT_PROTECTED` | short terms (not truncated) |
| `GENERIC_ADJ`, `OCR_ARTIFACTS` | fallback filters |
| `SKIP_LEFTOVER_NOUNS`, `TEMPORAL_PLACE_LEMMAS` | service nouns |

**Domain extension:**

```python
from nl2prolog import TextToProlog
TextToProlog.ATTR_LABEL_NOUNS |= {'метрика', 'выборка', 'гипотеза'}
TextToProlog.NER_ORG_BLACKLIST |= {'регламент', 'постановление'}
TextToProlog.SHORT_PROTECTED |= {'оки', 'мвт', 'гкал'}
```

The file `noise_ru.txt` (in the `nl2prolog` directory) — extends `ATTR_ADJ_WHITELIST` without code changes.

### 11.3. `nl2prolog` v1.0.2 Capabilities

**Grammatical frames:**

| NL | Query |
|---|---|
| "What is X?" | `node(X, [], T)` |
| "How much X in Y?" | `attribute(Y, количество_X, V)` |
| "When \<participle\> X?" | `attribute(X, год_\<verbal_noun_gen\>, V)` |
| "Does Y have X?" | `edge(Y, X, 'иметь')` |
| "Does X have Y?" | `edge(X, Y, 'иметь')` |
| "Who has X?" | `edge(X_var, X, 'иметь')` |
| "What X are in Y?" | `edge(X, Y, 'находиться_в')` |
| "Who owns Tesla?" | `edge(X, 'tesla', 'владеть')` (position-first wh) |
| "Where is X located?" | `edge(X, Y, 'находиться_в')` (wh-locative) |

**Plus:** URL filter, Unicode typography normalization (`’` → `'`, `—` → `-`), strict propagation, compound-merge UD (`технопарк_москва`, `флот_россия`).

---

## 12. Migration

### 12.1. From v5.13 → v5.14 (`app.py` + `graph_model.py`)

**Added in `graph_model.py`:**
- `KnowledgeGraph.merge(other)` — additive merge of another graph into the current one; returns `{added_*, skipped_*}`.
- `KnowledgeGraph.merge_from_prolog(text)` — wrapper: `merge(from_prolog(text))`.

**Added in `app.py`:**
- The `🔀 Merge` button in the project row.
- The `h_merge_file()` handler — opens a `.pl` file dialog, parses and merges.
- A separate `project_status` — an HTML box under the statistics, always visible (without expanding an accordion).
- `import_status` removed; `open`/`new`/`example`/`merge` write to `project_status`.
- `dlg_state` is **not reset** on merge.

**Backward compatibility:**
- The `from_prolog`/`to_prolog` API is unchanged — old `.pl` files are read.
- If you have an old `graph_model.py` without `merge`, `🔀 Merge` will fail with `AttributeError` — update `graph_model.py`.

### 12.2. From v5.12 → v5.13 (`app.py`)

**Added:**
- The **"💬 Dialog"** tab — `ask`/`answer`/`yes`/`no`/`reset` via `DialogTurn`.
- 6 dialog handlers: `h_dialog_ask`, `h_dialog_answer`, `h_dialog_yes`, `h_dialog_no`, `h_dialog_reset` + helpers `_apply_facts_local`, `_dialog_hint_for_no_solution`.
- Facts from NL statements are **automatically applied** to the graph.
- The "⏳ Pending question" panel.
- `dlg_state` reset when the extractor changes and on a full graph replacement.
- Diagnostics: `dialog_active`, `dialog_pending`.

**Backward compatibility:** all other handlers, theme, CSS, wiring — unchanged.

### 12.3. From v5.12 → v5.13 (`graph_layout.py`)

- `_PYVIS_OPTIONS`: removed `avoidOverlap`, `smooth.type: "continuous"`, `stabilization.iterations: 300`.
- `_PYVIS_FREEZE_JS`: physics is frozen on `stabilizationIterationsDone` + a timeout fallback.

**Fix symptom:** the PyVis graph no longer "jitters" or "rotates" after loading.

### 12.4. From v5.12 → v5.13 (`nl2prolog` v1.0.2)

- Possessive frames: "Does X have Y?", "Who has X?".
- URL filter + Unicode normalization.
- Transcript prints `solutions` with bindings.
- `DialogTurn.ask()` clears pending on a successful answer.

### 12.5. From v5.11.14 → v5.12 (`app.py`)

- The `dialog.py` import is wrapped in `try/except` — the editor starts without `nl2prolog`.
- Added `_NL2PROLOG_OK`, `_NL2PROLOG_VERSION`.
- The `_nl_package_status_html()` function — the banner in the NL accordion.
- The "⚙️ Custom converter" accordion is open by default when the extractor is absent.
- Diagnostics extended.

### 12.6. Extracting `text_to_prolog.py` → `nl2prolog`

**If you previously had a local `text_to_prolog.py`:**
- It is now a **shim** over `nl2prolog`. The logic is in the package.
- **Import API:** `from nl2prolog import TextToProlog` (instead of `from text_to_prolog import …`).
- **Backward compatibility:** `from text_to_prolog import …` continues to work via the shim.

**If you don't install `nl2prolog`:** the editor still works, but NL import requires a custom `.py`. Dialog is unavailable.

---

## What to Do If Something Doesn't Work

**Quick diagnostics:**

1. Open the **"🔬 Diagnostics"** accordion → **🔄 Show**.
2. Look at the JSON:
   - `pyagent: false` → queries unavailable (install PyAgentProlog).
   - `t2p_ok: false` and `nl2prolog_ok: false` → NL import unavailable.
   - `nl2prolog_ok: false` but `t2p_ok: true` → a local shim is working.
   - `t2p_custom: true` → a custom extractor is active.
   - `dialog_ok: false` → dialog unavailable (install `nl2prolog`).
   - `dialog_active: false` → dialog hasn't been started in this session yet.
   - `dialog_pending: true` → there's a pending question (press ✅/❌).
3. Check the banner in the NL accordion — it shows the main message.
4. Check the banner in the "💬 Dialog" tab — if dialog is unavailable, there's an orange message there.
5. For project operations — see the **"Project status"** box under the statistics: it has messages about `📂 Open`, `🔀 Merge`, `🆕 Create`, `📚 Demo`, `💾 Save`.

**If that didn't help** — send:
- The JSON from diagnostics.
- The console fragment at `python -m kg_editor` startup.
- Versions: `python --version`, `pip show nl2prolog gradio pyvis`.
- A screenshot of the problematic tab.

---

When updating `nl2prolog` to v1.1+, see the package CHANGELOG — the editor API doesn't change, but the internal capabilities of NL import and dialog may expand.
