"""KnowledgeGraph Editor — Gradio Blocks UI (PyAgentProlog backend).

Движок запросов — PyAgentProlog (prolog.agent.Agent).
Формат графа совместим с text_to_prolog._to_graph_program:

    node(Id, Props, Type).
    edge(Source, Target, Predicate).
    attribute(Entity, Name, Value).

Поверх фактов автоматически добавляются удобные правила:

    node(Id, Type) :- node(Id, _, Type).
    edge(S, T) :- edge(S, T, _).

Поэтому в запросах можно писать:
    node(apple, X)
    edge(X, Y, owns)
    attribute(X, release_year, Y)
    \\+(node(X, person))
    findall(X, edge(apple, X, _), L)

Каждый запрос строится на свежем агенте — мутации через assertz/retract
живут только в рамках одного запроса и не влияют на модель графа.

Редактор: цветные HTML-таблицы + полноценная подсветка Prolog-исходника.
NL-импорт: встроенный text_to_prolog.py или любой пользовательский .py
с классом TextToProlog (выбирается через UI).
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys as _sys
import traceback
import uuid as _uuid
from html import escape as _esc
from typing import Any, Dict, List, Optional, Tuple

import gradio as gr

# ---------------------------------------------------------------------
# Безопасное определение версии Gradio (защита от букв вроде 4.0.0b1)
# ---------------------------------------------------------------------
try:
    _GRADIO_VERSION = tuple(int(x) for x in gr.__version__.split('.')[:2])
except ValueError:
    _GRADIO_VERSION = (4, 0)  # Fallback на старую логику

# Gradio 6.0 переместил theme/css/head из Blocks() в launch().
_LAUNCH_THEME = _GRADIO_VERSION >= (6, 0)

# ---------------------------------------------------------------------
# Импорты локальных модулей (поддержка и пакета, и одиночного скрипта)
# ---------------------------------------------------------------------
try:
    from .graph_model import KnowledgeGraph
    from .graph_layout import render_pyvis
except ImportError:
    from graph_model import KnowledgeGraph
    from graph_layout import render_pyvis

# ---------------------------------------------------------------------
# PyAgentProlog (опционально)
# ---------------------------------------------------------------------
try:
    from prolog.agent import Agent  # type: ignore
    _AGENT_OK = True
    _AGENT_ERR = ""
except Exception as _e:  # noqa: BLE001
    Agent = None  # type: ignore
    _AGENT_OK = False
    _AGENT_ERR = str(_e)

# ---------------------------------------------------------------------
# NL-импорт (опционально; пользователь может заменить через UI)
# ---------------------------------------------------------------------
try:
    try:
        from .text_to_prolog import TextToProlog  # type: ignore
    except ImportError:
        from text_to_prolog import TextToProlog  # type: ignore
    _T2P_OK = True
except Exception:
    TextToProlog = None  # type: ignore
    _T2P_OK = False


# =====================================================================
# Константы
# =====================================================================
_CONVENIENCE_RULES = """
% --- convenience rules (добавлены редактором) ---
node(Id, Type) :- node(Id, _, Type).
edge(S, T) :- edge(S, T, _).
"""

_SOLUTION_LIMIT = 1000


# =====================================================================
# Тема (GitHub-dark) + принудительный dark
# =====================================================================
def _make_theme() -> gr.themes.Base:
    t = gr.themes.Base(
        primary_hue=gr.themes.colors.blue,
        neutral_hue=gr.themes.colors.slate,
    )
    return t.set(
        body_background_fill="#0b0d11",
        body_background_fill_dark="#0b0d11",
        body_text_color="#c7cbd1",
        body_text_color_dark="#c7cbd1",
        body_text_color_subdued="#8b949e",
        body_text_color_subdued_dark="#8b949e",

        block_background_fill="#0b0d11",
        block_background_fill_dark="#0b0d11",
        block_border_color="#2a313d",
        block_border_color_dark="#2a313d",
        block_label_background_fill="#0b0d11",
        block_label_background_fill_dark="#0b0d11",
        block_label_text_color="#8b949e",
        block_label_text_color_dark="#8b949e",
        block_title_text_color="#c7cbd1",
        block_title_text_color_dark="#c7cbd1",
        block_shadow="none",
        block_radius="6px",

        panel_background_fill="#0f1115",
        panel_background_fill_dark="#0f1115",
        panel_border_color="#2a313d",
        panel_border_color_dark="#2a313d",
        background_fill_primary="#0b0d11",
        background_fill_primary_dark="#0b0d11",
        background_fill_secondary="#0f1115",
        background_fill_secondary_dark="#0f1115",

        input_background_fill="#0b0d11",
        input_background_fill_dark="#0b0d11",
        input_border_color="#2a313d",
        input_border_color_dark="#2a313d",
        input_border_color_focus="#58a6ff",
        input_border_color_focus_dark="#58a6ff",
        input_placeholder_color="#6e7681",
        input_placeholder_color_dark="#6e7681",

        button_secondary_background_fill="#21262d",
        button_secondary_background_fill_dark="#21262d",
        button_secondary_background_fill_hover="#30363d",
        button_secondary_background_fill_hover_dark="#30363d",
        button_secondary_text_color="#c7cbd1",
        button_secondary_text_color_dark="#c7cbd1",
        button_secondary_border_color="#2a313d",
        button_secondary_border_color_dark="#2a313d",

        button_primary_background_fill="#238636",
        button_primary_background_fill_dark="#238636",
        button_primary_background_fill_hover="#2ea043",
        button_primary_background_fill_hover_dark="#2ea043",
        button_primary_text_color="#ffffff",
        button_primary_text_color_dark="#ffffff",

        table_even_background_fill="#0b0d11",
        table_even_background_fill_dark="#0b0d11",
        table_odd_background_fill="#0f1115",
        table_odd_background_fill_dark="#0f1115",
        table_border_color="#2a313d",
        table_border_color_dark="#2a313d",

        code_background_fill="#0b0d11",
        code_background_fill_dark="#0b0d11",

        color_accent_soft="#1c212a",
        color_accent_soft_dark="#1c212a",
        link_text_color="#79c0ff",
        link_text_color_dark="#79c0ff",
        link_text_color_hover="#a5d6ff",
        link_text_color_hover_dark="#a5d6ff",
        link_text_color_visited="#79c0ff",
        link_text_color_visited_dark="#79c0ff",

        container_radius="6px",
        shadow_drop="0 1px 3px rgba(0,0,0,0.6)",
        shadow_drop_lg="0 4px 12px rgba(0,0,0,0.6)",
    )


_DARK_FORCE_HEAD = """
<script>
(function () {
    const force = () => {
        document.documentElement.classList.add('dark');
        if (document.body) document.body.classList.add('dark');
    };
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', force);
    } else { force(); }
    new MutationObserver(() => {
        if (!document.documentElement.classList.contains('dark')) {
            document.documentElement.classList.add('dark');
        }
    }).observe(document.documentElement,
               { attributes: true, attributeFilter: ['class'] });
})();
</script>
"""


# =====================================================================
# CSS
# =====================================================================
_GLOBAL_CSS = """
.gradio-container {
    max-width: 1900px !important;
    padding: 6px 8px !important;
    background: #0b0d11 !important;
    color: #c7cbd1 !important;
}
footer { display: none !important; }

.gradio-container, .gradio-container * { color: #c7cbd1; }
.gradio-container a, .gradio-container a:visited { color: #79c0ff !important; }

button.compact-btn, .compact-btn button {
    min-height: 26px !important;
    padding: 2px 8px !important;
    font-size: 12px !important;
    line-height: 1.2 !important;
    background: #21262d !important;
    border: 1px solid #2a313d !important;
    color: #c7cbd1 !important;
}
button.compact-btn:hover, .compact-btn button:hover {
    background: #30363d !important;
    border-color: #3a4250 !important;
}

.compact-tb input, .compact-tb textarea {
    padding: 3px 7px !important;
    font-size: 12px !important;
    min-height: 26px !important;
    background: #0b0d11 !important;
    color: #c7cbd1 !important;
    border: 1px solid #2a313d !important;
}
.compact-tb input:focus, .compact-tb textarea:focus {
    border-color: #58a6ff !important;
    box-shadow: 0 0 0 2px rgba(88,166,255,.2) !important;
}

.compact-lbl label {
    font-size: 11px !important;
    margin-bottom: 1px !important;
    color: #8b949e !important;
}

.gradio-container input[type="text"],
.gradio-container input[type="number"],
.gradio-container textarea,
.gradio-container select {
    background: #0b0d11 !important;
    color: #c7cbd1 !important;
    border-color: #2a313d !important;
}
.gradio-container input:focus,
.gradio-container textarea:focus,
.gradio-container select:focus {
    border-color: #58a6ff !important;
    outline: none !important;
}
.gradio-container input[type="checkbox"] { accent-color: #58a6ff; }

.gradio-container .block,
.gradio-container .form {
    background: #0b0d11 !important;
    border-color: #2a313d !important;
}

.cm-editor { background: #0b0d11 !important; color: #e6e6e6 !important; }
.cm-editor .cm-gutters {
    background: #0f1115 !important;
    color: #6e7681 !important;
    border-right: 1px solid #2a313d !important;
}
.cm-editor .cm-activeLine { background: #161a20 !important; }
.cm-editor .cm-activeLineGutter { background: #161a20 !important; }
.cm-editor .cm-selectionBackground,
.cm-editor .cm-content ::selection { background: #2a313d !important; }
.cm-editor .cm-cursor { border-left-color: #79c0ff !important; }

.gradio-container table { background: #0b0d11 !important; }
.gradio-container th {
    background: #0f1115 !important;
    color: #8b949e !important;
    border-color: #2a313d !important;
}
.gradio-container td {
    background: #0b0d11 !important;
    color: #c7cbd1 !important;
    border-color: #2a313d !important;
}

.gradio-container .json-holder,
.gradio-container .json-viewer,
.gradio-container .json-container {
    background: #0b0d11 !important;
    color: #c7cbd1 !important;
    border: 1px solid #2a313d !important;
    border-radius: 4px;
}

.gradio-container .dropdown-menu,
.gradio-container ul.options {
    background: #0f1115 !important;
    border: 1px solid #2a313d !important;
}
.gradio-container .dropdown-menu li,
.gradio-container ul.options li { color: #c7cbd1 !important; }
.gradio-container .dropdown-menu li:hover,
.gradio-container ul.options li:hover { background: #161a20 !important; }

.gradio-container .tab-nav {
    border-bottom: 1px solid #2a313d !important;
    background: transparent !important;
}
.gradio-container .tab-nav button {
    color: #8b949e !important;
    background: transparent !important;
    border-bottom: 2px solid transparent !important;
}
.gradio-container .tab-nav button.selected {
    color: #c7cbd1 !important;
    border-bottom-color: #58a6ff !important;
}
.gradio-container .tabs { border-color: #2a313d !important; }

.gradio-container .accordion {
    border: 1px solid #2a313d !important;
    border-radius: 4px;
    background: #0b0d11 !important;
}
.gradio-container .accordion button.label-wrap,
.gradio-container .accordion .label-wrap {
    background: #0f1115 !important;
    color: #c7cbd1 !important;
}

pre.status-box {
    margin: 0 !important;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 11px;
    line-height: 1.35;
    padding: 4px 8px;
    background: #0b0d11;
    border: 1px solid #2a313d;
    border-radius: 4px;
    color: #c7cbd1;
    white-space: pre-wrap;
    max-height: 100px;
    overflow: auto;
}
.proj-info {
    font-size: 11px;
    line-height: 1.35;
    color: #8b949e;
    padding: 4px 8px;
    background: #0b0d11;
    border: 1px solid #2a313d;
    border-radius: 4px;
    word-break: break-all;
}
.proj-info b { color: #c7cbd1; }
.proj-info code { color: #79c0ff; background: transparent !important; }
.col-head {
    font-size: 14px !important;
    font-weight: 600;
    margin: 2px 0 6px 0 !important;
    color: #c7cbd1;
}
.gradio-container .html-container { background: transparent !important; }

.gradio-container .prose { color: #c7cbd1; }
.gradio-container .prose code {
    background: #1c212a !important;
    color: #e6e6e6 !important;
    padding: 1px 4px;
    border-radius: 3px;
}
.gradio-container .prose pre {
    background: #0b0d11 !important;
    border: 1px solid #2a313d !important;
}

*::-webkit-scrollbar { width: 8px; height: 8px; }
*::-webkit-scrollbar-track { background: transparent; }
*::-webkit-scrollbar-thumb { background: #2a313d; border-radius: 5px; }
*::-webkit-scrollbar-thumb:hover { background: #3a4250; }
"""


# =====================================================================
# Утилиты — базовые
# =====================================================================
def _status_html(s: str) -> str:
    return f'<pre class="status-box">{_esc(str(s))}</pre>'


def _safe(g) -> KnowledgeGraph:
    return g if isinstance(g, KnowledgeGraph) else KnowledgeGraph()


def _stats_html(g: KnowledgeGraph) -> str:
    s = g.summary()
    return (
        '<div class="proj-info">'
        f'<b>Узлов:</b> {s["nodes"]} &nbsp; '
        f'<b>Рёбер:</b> {s["edges"]} &nbsp; '
        f'<b>Атрибутов:</b> {s["attributes"]}'
        '</div>'
    )


def _graph_to_program(g: KnowledgeGraph) -> str:
    return g.to_prolog() + _CONVENIENCE_RULES


# =====================================================================
# Цветные чипы / цвета типов
# =====================================================================
_NODE_TYPE_COLORS: Dict[str, str] = {
    "concept": "#58a6ff",
    "person":  "#7ee787",
    "org":     "#f0883e",
    "organization": "#f0883e",
    "place":   "#d2a8ff",
    "loc":     "#d2a8ff",
    "event":   "#ff7b72",
    "thing":   "#79c0ff",
    "product": "#ffa657",
    "default": "#8b949e",
}


def _node_type_color(t: str) -> str:
    return _NODE_TYPE_COLORS.get((t or "").lower(), _NODE_TYPE_COLORS["default"])


def _chip(label: str, color: str, mono: bool = False) -> str:
    font = ("ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
            if mono else
            "ui-sans-serif,system-ui,sans-serif")
    return (
        f'<span style="display:inline-block;padding:1px 8px;'
        f'border-radius:10px;background:{color}22;color:{color};'
        f'border:1px solid {color}66;font-size:11px;'
        f'font-family:{font};line-height:1.6;white-space:nowrap;">'
        f'{_esc(label)}</span>'
    )


def _empty_table_html(msg: str) -> str:
    return (
        '<div style="padding:16px;color:#6e7681;text-align:center;'
        'border:1px dashed #2a313d;border-radius:4px;font-size:12px;'
        'font-family:ui-sans-serif,system-ui,sans-serif;">'
        f'{_esc(msg)}</div>'
    )


def _table_wrap(headers: List[str], rows: List[str],
                align: Optional[List[str]] = None) -> str:
    if align is None:
        align = ["left"] * len(headers)
    ths = "".join(
        f'<th style="padding:5px 10px;'
        f'text-align:{"right" if a == "right" else "left"};'
        f'color:#8b949e;font-size:11px;font-weight:600;'
        f'border-bottom:1px solid #2a313d;background:#0f1115;'
        f'font-family:ui-sans-serif,system-ui,sans-serif;'
        f'position:sticky;top:0;z-index:1;">{_esc(h)}</th>'
        for h, a in zip(headers, align)
    )
    return (
        '<div style="border:1px solid #2a313d;border-radius:4px;'
        'overflow:auto;max-height:380px;background:#0b0d11;">'
        '<table style="width:100%;border-collapse:collapse;font-size:12px;'
        'font-family:ui-sans-serif,system-ui,sans-serif;">'
        f'<thead><tr>{ths}</tr></thead>'
        '<tbody>'
        + "".join(rows) +
        '</tbody></table></div>'
    )


# =====================================================================
# Цветные таблицы
# =====================================================================
def _nodes_html(g: KnowledgeGraph) -> str:
    deg: Dict[str, int] = {n: 0 for n in g.nodes}
    for e in g.edges:
        if e.source in deg:
            deg[e.source] += 1
        if e.target in deg:
            deg[e.target] += 1
    if not g.nodes:
        return _empty_table_html("Нет узлов")
    rows: List[str] = []
    for n in g.nodes.values():
        color = _node_type_color(n.type)
        rows.append(
            "<tr>"
            f'<td style="padding:4px 10px;border-bottom:1px solid #161a20;'
            f'font-family:ui-monospace,monospace;color:#79c0ff;">'
            f'{_esc(n.id)}</td>'
            f'<td style="padding:4px 10px;border-bottom:1px solid #161a20;">'
            f'{_chip(n.type, color)}</td>'
            f'<td style="padding:4px 10px;border-bottom:1px solid #161a20;'
            f'text-align:right;color:#8b949e;font-family:ui-monospace,monospace;">'
            f'{deg[n.id]}</td>'
            "</tr>"
        )
    return _table_wrap(["id", "type", "degree"], rows,
                       align=["left", "left", "right"])


def _edges_html(g: KnowledgeGraph) -> str:
    if not g.edges:
        return _empty_table_html("Нет рёбер")
    rows: List[str] = []
    for i, e in enumerate(g.edges):
        src_color = (_node_type_color(g.nodes[e.source].type)
                     if e.source in g.nodes else "#8b949e")
        tgt_color = (_node_type_color(g.nodes[e.target].type)
                     if e.target in g.nodes else "#8b949e")
        rows.append(
            "<tr>"
            f'<td style="padding:4px 10px;border-bottom:1px solid #161a20;'
            f'color:#6e7681;text-align:right;font-family:ui-monospace,monospace;'
            f'width:32px;">{i}</td>'
            f'<td style="padding:4px 10px;border-bottom:1px solid #161a20;">'
            f'{_chip(e.source, src_color, mono=True)}</td>'
            f'<td style="padding:4px 10px;border-bottom:1px solid #161a20;'
            f'color:#ff7b72;font-family:ui-monospace,monospace;'
            f'white-space:nowrap;font-size:11px;">'
            f'─[{_esc(e.predicate)}]→</td>'
            f'<td style="padding:4px 10px;border-bottom:1px solid #161a20;">'
            f'{_chip(e.target, tgt_color, mono=True)}</td>'
            "</tr>"
        )
    return _table_wrap(["idx", "source", "predicate", "target"], rows,
                       align=["right", "left", "center", "left"])


def _attrs_html(g: KnowledgeGraph) -> str:
    if not g.attributes:
        return _empty_table_html("Нет атрибутов")
    rows: List[str] = []
    for i, a in enumerate(g.attributes):
        color = (_node_type_color(g.nodes[a.entity].type)
                 if a.entity in g.nodes else "#8b949e")
        rows.append(
            "<tr>"
            f'<td style="padding:4px 10px;border-bottom:1px solid #161a20;'
            f'color:#6e7681;text-align:right;font-family:ui-monospace,monospace;'
            f'width:32px;">{i}</td>'
            f'<td style="padding:4px 10px;border-bottom:1px solid #161a20;">'
            f'{_chip(a.entity, color, mono=True)}</td>'
            f'<td style="padding:4px 10px;border-bottom:1px solid #161a20;'
            f'color:#79c0ff;font-family:ui-monospace,monospace;">'
            f'{_esc(a.name)}</td>'
            f'<td style="padding:4px 10px;border-bottom:1px solid #161a20;'
            f'color:#ffa657;font-family:ui-monospace,monospace;">'
            f'= {_esc(a.value)}</td>'
            "</tr>"
        )
    return _table_wrap(["idx", "entity", "name", "value"], rows,
                       align=["right", "left", "left", "left"])


# =====================================================================
# Подсветка Prolog
# =====================================================================
_PL_TOKEN_RE = re.compile(
    r"""
    (%[^\n]*)                                    # 1 line comment
  | (/\*.*?\*/)                                  # 2 block comment
  | ('(?:\\.|[^'\\])*')                          # 3 quoted atom
  | ("(?:\\.|[^"\\])*")                          # 4 string
  | (:-|->)                                      # 5 directive / ifthen
  | ([\[\]\(\)\.,;\|])                           # 6 punctuation
  | (!)                                          # 7 cut
  | (\\\+)                                       # 8 not
  | (\b(?:is|mod|div|rem|xor|not|true|fail)\b)   # 9 keywords
  | ([A-Z_][A-Za-z0-9_]*)                        # 10 variable
  | (\d+(?:\.\d+)?)                              # 11 number
  | ([a-z][A-Za-z0-9_]*)                         # 12 atom
  | ([+\-*/=<>@\\^&~:]+)                         # 13 operators
  | (\s+)                                        # 14 whitespace
  | (.)                                          # 15 anything
    """,
    re.VERBOSE | re.DOTALL,
)


def _prolog_syntax_html(src: str) -> str:
    parts: List[str] = []
    for m in _PL_TOKEN_RE.finditer(src or ""):
        g = m.groups()
        raw = m.group(0)
        if g[0] or g[1]:        # comment
            parts.append(f'<span style="color:#7ee787;font-style:italic;">'
                         f'{_esc(raw)}</span>')
        elif g[2] or g[3]:      # quoted atom / string
            parts.append(f'<span style="color:#ffa657;">{_esc(raw)}</span>')
        elif g[4]:              # :-  ->
            parts.append(f'<span style="color:#ff7b72;font-weight:600;">'
                         f'{_esc(raw)}</span>')
        elif g[5]:              # punctuation
            parts.append(f'<span style="color:#8b949e;">{_esc(raw)}</span>')
        elif g[6]:              # !
            parts.append(f'<span style="color:#ff7b72;font-weight:600;">'
                         f'!</span>')
        elif g[7]:              # \+
            parts.append(f'<span style="color:#ff7b72;">{_esc(raw)}</span>')
        elif g[8]:              # keywords
            parts.append(f'<span style="color:#ff7b72;">{_esc(raw)}</span>')
        elif g[9]:              # variable
            parts.append(f'<span style="color:#79c0ff;">{_esc(raw)}</span>')
        elif g[10]:             # number
            parts.append(f'<span style="color:#d2a8ff;">{_esc(raw)}</span>')
        elif g[11]:             # atom
            parts.append(f'<span style="color:#c7cbd1;">{_esc(raw)}</span>')
        elif g[12]:             # operators
            parts.append(f'<span style="color:#ff7b72;">{_esc(raw)}</span>')
        else:
            parts.append(_esc(raw))
    return "".join(parts)


def _prolog_code_html(src: str) -> str:
    if not src or not src.strip():
        return _empty_table_html(
            "Нажмите 🔄 «Обновить из графа» для сериализации")
    return (
        '<pre style="margin:0;padding:8px 10px;background:#0b0d11;'
        'border:1px solid #2a313d;border-radius:4px;color:#c7cbd1;'
        'font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;'
        'font-size:12px;line-height:1.55;white-space:pre;overflow:auto;'
        'max-height:380px;">'
        + _prolog_syntax_html(src) +
        '</pre>'
    )


# =====================================================================
# Refresh — единый кортеж для всех таблиц
# =====================================================================
def _refresh(g: KnowledgeGraph):
    return (
        g,
        _nodes_html(g),
        _edges_html(g),
        _attrs_html(g),
        gr.update(choices=_node_choices(g), value=None),
        gr.update(choices=_edge_choices(g), value=None),
        gr.update(choices=_attr_choices(g), value=None),
        _stats_html(g),
        render_pyvis(g),
    )


def _node_choices(g: KnowledgeGraph) -> List[str]:
    return list(g.nodes.keys())


def _edge_choices(g: KnowledgeGraph) -> List[Tuple[str, str]]:
    return [(f"{i}: {e.source} —[{e.predicate}]→ {e.target}", str(i))
            for i, e in enumerate(g.edges)]


def _attr_choices(g: KnowledgeGraph) -> List[Tuple[str, str]]:
    return [(f"{i}: {a.entity}.{a.name} = {a.value}", str(i))
            for i, a in enumerate(g.attributes)]


def _serialize_and_preview(g):
    """Возвращает (src_text, colored_html) для синхронизации src_code+src_preview."""
    src = g.to_prolog() if isinstance(g, KnowledgeGraph) else ""
    return src, _prolog_code_html(src)


# ---- Диалоги выбора файлов -------------------------------------------
def _pick_file(initial: str = "", title: str = "Выберите файл",
               save: bool = False,
               filetypes: Optional[List[Tuple[str, str]]] = None
               ) -> Optional[str]:
    """Нативный диалог выбора/сохранения файла.

    filetypes: список (label, patterns) — по умолчанию .pl + все файлы.
    """
    if filetypes is None:
        filetypes = [("Prolog (*.pl)", "*.pl"), ("All files", "*.*")]
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as e:
        print(f"[_pick_file] tkinter unavailable: {e}")
        return None
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        init_dir = initial if (initial and os.path.isdir(initial)) \
            else os.path.expanduser("~")
        if save:
            p = filedialog.asksaveasfilename(
                initialdir=init_dir, title=title,
                defaultextension=".pl",
                filetypes=filetypes,
            )
        else:
            p = filedialog.askopenfilename(
                initialdir=init_dir, title=title,
                filetypes=filetypes,
            )
        root.destroy()
        return p or None
    except Exception as e:
        print(f"[_pick_file] {e}")
        return None


def _pick_folder(initial: str = "", title: str = "Папка проекта") -> Optional[str]:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as e:
        print(f"[_pick_folder] tkinter unavailable: {e}")
        return None
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        p = filedialog.askdirectory(
            initialdir=initial or os.path.expanduser("~"),
            title=title, mustexist=False,
        )
        root.destroy()
        return p or None
    except Exception as e:
        print(f"[_pick_folder] {e}")
        return None


# =====================================================================
# Загрузка пользовательского TextToProlog из .py-файла
# =====================================================================
def _h_pick_t2p() -> str:
    """Открыть диалог и вернуть выбранный путь к .py-модулю."""
    p = _pick_file(
        title="Выберите модуль text-to-prolog (.py)",
        filetypes=[("Python (*.py)", "*.py"), ("All files", "*.*")],
    )
    return p or ""


def h_load_t2p_module(path: str):
    """Загружает класс TextToProlog из указанного .py-файла.

    Возвращает (класс | None, HTML-статус).

    Порядок:
      1. Проверить путь (файл существует, это .py).
      2. Добавить папку файла в sys.path (для локальных импортов внутри модуля).
      3. Загрузить через importlib с уникальным именем (чтобы не
         конфликтовать с уже импортированными модулями).
      4. Проверить наличие класса TextToProlog и его инстанцируемость.
      5. В случае ошибки — очистить sys.modules и вернуть None.
    """
    path = (path or "").strip()
    if not path:
        return None, _status_html("✗ Укажите путь к .py-файлу")
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return None, _status_html(f"✗ Файл не найден: {path}")
    if not path.endswith(".py"):
        return None, _status_html(
            f"✗ Ожидался .py-файл, получено: {path}")

    mod_dir = os.path.dirname(path)
    if mod_dir and mod_dir not in _sys.path:
        _sys.path.insert(0, mod_dir)

    unique_name = f"_kg_editor_custom_t2p_{_uuid.uuid4().hex[:8]}"
    try:
        spec = importlib.util.spec_from_file_location(unique_name, path)
        if spec is None or spec.loader is None:
            return None, _status_html(
                f"✗ Не удалось создать загрузчик для: {path}")
        module = importlib.util.module_from_spec(spec)
        _sys.modules[unique_name] = module
        spec.loader.exec_module(module)
    except Exception as e:  # noqa: BLE001
        _sys.modules.pop(unique_name, None)
        return None, _status_html(
            f"✗ Ошибка импорта {path}:\n{e}\n\n{traceback.format_exc()}")

    if not hasattr(module, "TextToProlog"):
        _sys.modules.pop(unique_name, None)
        return None, _status_html(
            f"✗ В модуле нет класса TextToProlog: {path}")

    cls = module.TextToProlog
    try:
        cls()  # sanity check: конструктор без аргументов
    except Exception as e:  # noqa: BLE001
        _sys.modules.pop(unique_name, None)
        return None, _status_html(
            f"✗ Класс TextToProlog не инициализируется без аргументов:\n"
            f"{e}")

    return cls, _status_html(
        f"✓ Загружен модуль: {path}\n"
        f"  класс: TextToProlog\n"
        f"  as sys.modules['{unique_name}']")


# =====================================================================
# Handlers — мутации графа
# =====================================================================
def h_add_node(g, nid, ntype):
    g = _safe(g)
    try:
        g.add_node(nid, ntype or "concept")
        return (*_refresh(g), "", "")
    except Exception as e:
        return (*_refresh(g), "", f"✗ {e}")


def h_del_node(g, nid):
    g = _safe(g)
    if nid:
        g.remove_node(nid)
    return _refresh(g)


def h_add_edge(g, src, tgt, pred):
    g = _safe(g)
    try:
        g.add_edge(src, tgt, pred)
        return (*_refresh(g), "", "", "")
    except Exception as e:
        return (*_refresh(g), "", "", f"✗ {e}")


def h_del_edge(g, idx_str):
    g = _safe(g)
    if idx_str is None:
        return _refresh(g)
    try:
        g.remove_edge(int(idx_str))
    except Exception:
        pass
    return _refresh(g)


def h_add_attr(g, ent, name, value):
    g = _safe(g)
    try:
        g.add_attribute(ent, name, value)
        return (*_refresh(g), "", "", "")
    except Exception as e:
        return (*_refresh(g), "", "", f"✗ {e}")


def h_del_attr(g, idx_str):
    g = _safe(g)
    if idx_str is None:
        return _refresh(g)
    try:
        g.remove_attribute(int(idx_str))
    except Exception:
        pass
    return _refresh(g)


# =====================================================================
# Handlers — импорт/экспорт/проект
# =====================================================================
def h_import_nl(g, text, t2p_cls=None):
    """Импорт графа из естественного языка.

    t2p_cls: пользовательский класс TextToProlog (или None — использовать
    встроенный). Класс должен предоставлять метод
    `convert(text, mode="graph") -> str`, возвращающий Prolog-исходник.
    """
    g = _safe(g)

    # Выбираем источник класса
    cls = t2p_cls if t2p_cls is not None else (TextToProlog if _T2P_OK else None)
    if cls is None:
        return _status_html(
            "✗ text_to_prolog недоступен. Выберите файл модуля "
            "в блоке «⚙️ Пользовательский конвертер» "
            "или положите text_to_prolog.py в sys.path.")

    if not (text or "").strip():
        return _status_html("✗ Пустой текст")

    source_label = (f"пользовательский ({getattr(cls, '__module__', '?')})"
                    if t2p_cls is not None else "встроенный")

    try:
        t2p = cls()
        prolog_src = t2p.convert(text, mode="graph")
        if not prolog_src.strip():
            return _status_html(
                f"✗ Не удалось извлечь факты (источник: {source_label})")
        new_g = KnowledgeGraph.from_prolog(prolog_src)
        for n in new_g.nodes.values():
            g.add_node(n.id, n.type, n.props)
        for e in new_g.edges:
            g.add_edge(e.source, e.target, e.predicate)
        for a in new_g.attributes:
            g.add_attribute(a.entity, a.name, a.value)
        return _status_html(
            f"✓ Импортировано ({source_label}): "
            f"+{len(new_g.nodes)} узлов, "
            f"+{len(new_g.edges)} рёбер, "
            f"+{len(new_g.attributes)} атрибутов")
    except Exception as e:  # noqa: BLE001
        return _status_html(f"✗ {e}\n{traceback.format_exc()}")


def h_parse_source(g, code):
    try:
        new_g = KnowledgeGraph.from_prolog(code or "")
        return _refresh(new_g)[0], _status_html(
            f"✓ Разобрано: узлов={len(new_g.nodes)}, "
            f"рёбер={len(new_g.edges)}, атрибутов={len(new_g.attributes)}")
    except Exception as e:
        return g, _status_html(f"✗ {e}")


def h_open_file(g):
    p = _pick_file(title="Открыть .pl графа",
                   filetypes=[("Prolog (*.pl)", "*.pl"),
                              ("All files", "*.*")])
    if not p:
        return _refresh(_safe(g)) + (_status_html("Файл не выбран"),)
    try:
        with open(p, encoding="utf-8") as f:
            text = f.read()
        new_g = KnowledgeGraph.from_prolog(text)
        return _refresh(new_g) + (
            _status_html(f"✓ Загружено: {p}\n"
                         f"  узлов={len(new_g.nodes)}, "
                         f"рёбер={len(new_g.edges)}"),)
    except Exception as e:
        return _refresh(_safe(g)) + (_status_html(f"✗ {e}"),)


def h_save_file(g, current_path):
    g = _safe(g)
    p = current_path or _pick_file(
        title="Сохранить граф как...", save=True,
        filetypes=[("Prolog (*.pl)", "*.pl"), ("All files", "*.*")])
    if not p:
        return _status_html("✗ Файл не выбран"), current_path
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write(g.to_prolog())
        return _status_html(f"✓ Сохранено: {p}"), p
    except Exception as e:
        return _status_html(f"✗ {e}"), current_path


def h_new_project(g):
    p = _pick_folder(title="Папка для нового графа")
    if not p:
        return _refresh(_safe(g)) + (_status_html("Отменено"),)
    try:
        os.makedirs(p, exist_ok=True)
        kb = os.path.join(p, "graph.pl")
        if not os.path.isfile(kb):
            with open(kb, "w", encoding="utf-8") as f:
                f.write("% Knowledge graph проект\n")
        new_g = KnowledgeGraph.from_prolog(
            open(kb, encoding="utf-8").read())
        return _refresh(new_g) + (_status_html(f"✓ Проект: {p}"),)
    except Exception as e:
        return _refresh(_safe(g)) + (_status_html(f"✗ {e}"),)


def h_load_example(g):
    demo = KnowledgeGraph()
    demo.add_node("apple", "org")
    demo.add_node("iphone", "thing")
    demo.add_node("smartphone", "concept")
    demo.add_node("elon_musk", "person")
    demo.add_node("spacex", "org")
    demo.add_edge("apple", "iphone", "releases")
    demo.add_edge("apple", "smartphone", "produces")
    demo.add_edge("elon_musk", "spacex", "owns")
    demo.add_attribute("iphone", "release_year", "2022")
    demo.add_attribute("spacex", "industry", "aerospace")
    return _refresh(demo) + (_status_html("✓ Демо-граф загружен"),)


# =====================================================================
# Запросы через PyAgentProlog
# =====================================================================
def h_query(g, text):
    g = _safe(g)
    text = (text or "").strip()
    if not text:
        return {"result": None}, "✗ Пустой запрос"
    if not _AGENT_OK:
        return ({"error": "PyAgentProlog (prolog.agent) недоступен",
                 "import_error": _AGENT_ERR},
                "✗ Установите пакет prolog в sys.path")

    q = text if text.endswith(".") else text + "."

    try:
        src = _graph_to_program(g)
        agent = Agent(src, context={})
    except Exception as e:  # noqa: BLE001
        return ({"error": str(e), "traceback": traceback.format_exc()},
                f"✗ Ошибка построения агента: {e}")

    sols: List[Any] = []
    truncated = False
    try:
        for item in agent.stream(q):
            if isinstance(item, dict) and 'error' in item:
                return {"error": item['error']}, f"✗ {item['error']}"
            if item is False:
                return {"result": False}, "✗ Нет решений"
            if item is True:
                return {"result": True}, "✓ true"
            if isinstance(item, dict):
                sols.append(item)
            if len(sols) >= _SOLUTION_LIMIT:
                truncated = True
                break
    except Exception as e:  # noqa: BLE001
        return ({"error": str(e), "traceback": traceback.format_exc()},
                f"✗ {e}")

    if not sols:
        return {"result": None}, "Нет решений"
    suffix = f" (лимит {_SOLUTION_LIMIT})" if truncated else ""
    return sols, f"✓ {len(sols)} решение(й){suffix}"


# =====================================================================
# UI
# =====================================================================
def build_ui() -> gr.Blocks:
    _blocks_kwargs: Dict[str, Any] = {
        "title": "KnowledgeGraph Editor (PyAgentProlog)",
    }
    # В Gradio <6 — передаём сюда; в Gradio ≥6 — в launch().
    if not _LAUNCH_THEME:
        _blocks_kwargs.update(
            css=_GLOBAL_CSS,
            theme=_make_theme(),
            head=_DARK_FORCE_HEAD,
        )

    with gr.Blocks(**_blocks_kwargs) as ui:
        graph_state = gr.State(KnowledgeGraph())
        current_path = gr.State("")
        t2p_cls_state = gr.State(None)   # загруженный пользовательский класс

        with gr.Row(equal_height=False):
            # ==========================================================
            # КОЛОНКА 1 — проект / импорт
            # ==========================================================
            with gr.Column(scale=2, min_width=300):
                gr.HTML('<div class="col-head">📁 Граф / Проект</div>')

                with gr.Row(equal_height=True):
                    open_btn = gr.Button("📂 Открыть", size="sm", scale=2,
                                         elem_classes=["compact-btn"])
                    new_btn = gr.Button("🆕 Создать", size="sm", scale=2,
                                        elem_classes=["compact-btn"])
                    save_btn = gr.Button("💾 Сохранить", size="sm", scale=2,
                                         elem_classes=["compact-btn"])
                    example_btn = gr.Button("📚", size="sm", scale=1,
                                            elem_classes=["compact-btn"])

                stats_html = gr.HTML(_stats_html(KnowledgeGraph()))

                with gr.Accordion("📝 Импорт из естественного языка",
                                  open=False):
                    nl_text = gr.Textbox(
                        placeholder="Илон Маск владеет SpaceX. "
                                    "Apple выпустила iPhone 14 в 2022.",
                        lines=4, show_label=False,
                        elem_classes=["compact-tb"],
                    )
                    nl_btn = gr.Button("✨ Извлечь в граф", size="sm",
                                       elem_classes=["compact-btn"])
                    nl_status = gr.HTML(_status_html(
                        "Готов." if _T2P_OK
                        else "Встроенный text_to_prolog.py недоступен — "
                             "выберите модуль ниже."))

                    # --- Выбор пользовательского конвертера ---
                    with gr.Accordion("⚙️ Пользовательский конвертер "
                                      "(опционально)", open=False):
                        gr.Markdown(
                            "По умолчанию используется встроенный "
                            "`text_to_prolog.py`. Можно указать другой "
                            "`.py`-файл с классом **`TextToProlog`** "
                            "и методом `convert(text, mode=\"graph\")`."
                        )
                        t2p_path_in = gr.Textbox(
                            placeholder="Путь к .py-файлу "
                                        "(можно выбрать кнопкой 📂)",
                            show_label=False, lines=1,
                            elem_classes=["compact-tb"],
                        )
                        with gr.Row(equal_height=True):
                            t2p_pick_btn = gr.Button(
                                "📂 Выбрать .py", size="sm",
                                elem_classes=["compact-btn"])
                            t2p_load_btn = gr.Button(
                                "✅ Загрузить", size="sm",
                                elem_classes=["compact-btn"])
                            t2p_reset_btn = gr.Button(
                                "↺ Встроенный", size="sm",
                                elem_classes=["compact-btn"])
                        t2p_status = gr.HTML(_status_html(
                            "Используется встроенный text_to_prolog.py"
                            if _T2P_OK
                            else "Встроенный недоступен — выберите файл вручную"))

                with gr.Accordion("📥 Импорт из Prolog", open=False):
                    import_code = gr.Code(
                        language=None, lines=8,
                        value="% Вставьте node/3, edge/3, attribute/3",
                    )
                    import_btn = gr.Button("📥 Разобрать", size="sm",
                                           elem_classes=["compact-btn"])
                    import_status = gr.HTML(_status_html("Готов."))

                with gr.Accordion("🔬 Диагностика", open=False):
                    diag_btn = gr.Button("🔄 Показать", size="sm",
                                         elem_classes=["compact-btn"])
                    diag_json = gr.JSON(label="", show_label=False)

            # ==========================================================
            # КОЛОНКА 2 — редактор
            # ==========================================================
            with gr.Column(scale=5, min_width=500):
                gr.HTML('<div class="col-head">🧩 Редактор графа</div>')

                with gr.Tabs():
                    # ---- Узлы ----
                    with gr.Tab("Узлы"):
                        nodes_tbl = gr.HTML(
                            _nodes_html(KnowledgeGraph()))
                        with gr.Row(equal_height=True):
                            nid_in = gr.Textbox(placeholder="id (apple)",
                                                show_label=False, scale=2,
                                                elem_classes=["compact-tb"])
                            ntype_in = gr.Textbox(
                                placeholder="type (org, person, ...)",
                                show_label=False, scale=2,
                                elem_classes=["compact-tb"])
                            add_node_btn = gr.Button("➕", size="sm", scale=1,
                                                     elem_classes=["compact-btn"])
                        with gr.Row(equal_height=True):
                            del_node_dd = gr.Dropdown(choices=[],
                                                      label="Удалить",
                                                      show_label=False,
                                                      scale=4)
                            del_node_btn = gr.Button("🗑️", size="sm", scale=1,
                                                     elem_classes=["compact-btn"])
                        node_msg = gr.Textbox(label="", show_label=False,
                                              interactive=False, lines=1,
                                              elem_classes=["compact-tb"])

                    # ---- Рёбра ----
                    with gr.Tab("Рёбра"):
                        edges_tbl = gr.HTML(
                            _edges_html(KnowledgeGraph()))
                        with gr.Row(equal_height=True):
                            esrc_in = gr.Textbox(placeholder="source",
                                                 show_label=False, scale=2,
                                                 elem_classes=["compact-tb"])
                            etgt_in = gr.Textbox(placeholder="target",
                                                 show_label=False, scale=2,
                                                 elem_classes=["compact-tb"])
                            epred_in = gr.Textbox(placeholder="predicate",
                                                  show_label=False, scale=2,
                                                  elem_classes=["compact-tb"])
                            add_edge_btn = gr.Button("➕", size="sm", scale=1,
                                                     elem_classes=["compact-btn"])
                        with gr.Row(equal_height=True):
                            del_edge_dd = gr.Dropdown(choices=[],
                                                      label="Удалить",
                                                      show_label=False,
                                                      scale=4)
                            del_edge_btn = gr.Button("🗑️", size="sm", scale=1,
                                                     elem_classes=["compact-btn"])
                        edge_msg = gr.Textbox(label="", show_label=False,
                                              interactive=False, lines=1,
                                              elem_classes=["compact-tb"])

                    # ---- Атрибуты ----
                    with gr.Tab("Атрибуты"):
                        attrs_tbl = gr.HTML(
                            _attrs_html(KnowledgeGraph()))
                        with gr.Row(equal_height=True):
                            aent_in = gr.Textbox(placeholder="entity",
                                                 show_label=False, scale=2,
                                                 elem_classes=["compact-tb"])
                            aname_in = gr.Textbox(placeholder="name",
                                                  show_label=False, scale=2,
                                                  elem_classes=["compact-tb"])
                            aval_in = gr.Textbox(placeholder="value",
                                                 show_label=False, scale=2,
                                                 elem_classes=["compact-tb"])
                            add_attr_btn = gr.Button("➕", size="sm", scale=1,
                                                     elem_classes=["compact-btn"])
                        with gr.Row(equal_height=True):
                            del_attr_dd = gr.Dropdown(choices=[],
                                                      label="Удалить",
                                                      show_label=False,
                                                      scale=4)
                            del_attr_btn = gr.Button("🗑️", size="sm", scale=1,
                                                     elem_classes=["compact-btn"])
                        attr_msg = gr.Textbox(label="", show_label=False,
                                              interactive=False, lines=1,
                                              elem_classes=["compact-tb"])

                    # ---- Prolog source ----
                    with gr.Tab("Prolog source"):
                        gr.HTML('<div class="col-head" '
                                'style="font-size:11px;">'
                                '🎨 Просмотр с подсветкой</div>')
                        src_preview = gr.HTML(
                            _prolog_code_html("")
                        )

                        with gr.Accordion("✏️ Редактировать исходник",
                                          open=False):
                            src_code = gr.Code(
                                language=None,
                                lines=18,
                                value="% Нажмите 🔄 для сериализации графа",
                            )

                        with gr.Row(equal_height=True):
                            serialize_btn = gr.Button(
                                "🔄 Обновить из графа", size="sm",
                                elem_classes=["compact-btn"])
                            parse_src_btn = gr.Button(
                                "📥 Применить из Prolog", size="sm",
                                elem_classes=["compact-btn"])
                        src_status = gr.HTML(_status_html("Готов."))

            # ==========================================================
            # КОЛОНКА 3 — визуализация + запросы
            # ==========================================================
            with gr.Column(scale=4, min_width=420):
                gr.HTML('<div class="col-head">🖼️ Визуализация (PyVis)</div>')
                graph_html = gr.HTML(render_pyvis(None))

                gr.HTML('<div class="col-head">🔎 Запросы (PyAgentProlog)</div>')
                query_in = gr.Textbox(
                    placeholder=(
                        "edge(X, Y, owns).\n"
                        "node(apple, T).\n"
                        "attribute(iphone, release_year, Y).\n"
                        "\\+ (node(X, person))\n"
                    ),
                    lines=3, show_label=False,
                    elem_classes=["compact-tb"],
                )
                with gr.Row(equal_height=True):
                    run_q_btn = gr.Button("▶ Запрос", size="sm",
                                          elem_classes=["compact-btn"])
                    help_btn = gr.Button("ℹ️ Помощь", size="sm",
                                         elem_classes=["compact-btn"])

                query_status = gr.Textbox(
                    label="", show_label=False, interactive=False, lines=1,
                    elem_classes=["compact-tb"],
                )
                query_out = gr.JSON(label="Решения", show_label=False)

                if not _AGENT_OK:
                    gr.Markdown(
                        f"⚠️ **PyAgentProlog не загружен**: `{_AGENT_ERR}`\n\n"
                        "Установите пакет `prolog` в `sys.path`."
                    )

        # ==========================================================
        # Wiring
        # ==========================================================
        refresh_outs = [
            graph_state, nodes_tbl, edges_tbl, attrs_tbl,
            del_node_dd, del_edge_dd, del_attr_dd,
            stats_html, graph_html,
        ]

        # --- пользовательский TextToProlog ---
        t2p_pick_btn.click(_h_pick_t2p, [], [t2p_path_in])
        t2p_load_btn.click(h_load_t2p_module, [t2p_path_in],
                           [t2p_cls_state, t2p_status])
        t2p_reset_btn.click(
            lambda: (
                None,
                _status_html(
                    "↺ Используется встроенный text_to_prolog.py"
                    if _T2P_OK
                    else "↺ Сброшено (встроенный недоступен)"),
            ),
            [], [t2p_cls_state, t2p_status])

        # --- импорт ---
        nl_btn.click(
            h_import_nl,
            [graph_state, nl_text, t2p_cls_state],
            [nl_status],
        ).then(lambda g: _refresh(g), [graph_state], refresh_outs)

        import_btn.click(h_parse_source, [graph_state, import_code],
                         [graph_state, src_status]).then(
            lambda g: _refresh(g), [graph_state], refresh_outs)

        # --- проект ---
        open_btn.click(h_open_file, [graph_state],
                       refresh_outs + [import_status]).then(
            _serialize_and_preview, [graph_state], [src_code, src_preview])

        new_btn.click(h_new_project, [graph_state],
                      refresh_outs + [import_status]).then(
            _serialize_and_preview, [graph_state], [src_code, src_preview])

        example_btn.click(h_load_example, [graph_state],
                          refresh_outs + [import_status]).then(
            _serialize_and_preview, [graph_state], [src_code, src_preview])

        save_btn.click(h_save_file, [graph_state, current_path],
                       [import_status, current_path])

        # --- узлы ---
        add_node_btn.click(h_add_node,
                           [graph_state, nid_in, ntype_in],
                           refresh_outs + [nid_in, node_msg])
        del_node_btn.click(h_del_node,
                           [graph_state, del_node_dd],
                           refresh_outs)

        # --- рёбра ---
        add_edge_btn.click(h_add_edge,
                           [graph_state, esrc_in, etgt_in, epred_in],
                           refresh_outs + [esrc_in, etgt_in, edge_msg])
        del_edge_btn.click(h_del_edge,
                           [graph_state, del_edge_dd],
                           refresh_outs)

        # --- атрибуты ---
        add_attr_btn.click(h_add_attr,
                           [graph_state, aent_in, aname_in, aval_in],
                           refresh_outs + [aent_in, aname_in, attr_msg])
        del_attr_btn.click(h_del_attr,
                           [graph_state, del_attr_dd],
                           refresh_outs)

        # --- Prolog source ---
        serialize_btn.click(_serialize_and_preview, [graph_state],
                            [src_code, src_preview])
        src_code.change(lambda s: _prolog_code_html(s or ""),
                        [src_code], [src_preview])
        parse_src_btn.click(h_parse_source,
                            [graph_state, src_code],
                            [graph_state, src_status]).then(
            lambda g: _refresh(g), [graph_state], refresh_outs)

        # --- запросы ---
        run_q_btn.click(h_query, [graph_state, query_in],
                        [query_out, query_status])

        def _help():
            return _status_html(
                "Доступно в запросах (PyAgentProlog):\n"
                "  node(Id, Type)\n"
                "  node(Id, Props, Type)\n"
                "  edge(S, T, Pred)\n"
                "  edge(S, T)\n"
                "  attribute(E, Name, Value)\n"
                "  \\+ goal, A, B, X = Y, X \\= Y\n"
                "  findall/3, bagof/3, setof/3, member/2, append/3,\n"
                "  length/2, atom/1, integer/1, compound/1, ground/1\n"
                "Примеры:\n"
                "  edge(X, Y, owns)\n"
                "  node(N, person)\n"
                "  attribute(E, release_year, Y), E = iphone\n"
                "  edge(A, B, _), \\+ (A = B)\n"
                "  findall(X, edge(apple, X, _), L)")

        help_btn.click(_help, [], [query_status])

        # --- диагностика ---
        def _diag(g, t2p_cls):
            g = _safe(g)
            info = {
                "summary": g.summary(),
                "pyagentprolog": _AGENT_OK,
                "text_to_prolog": (
                    "custom" if t2p_cls is not None else _T2P_OK
                ),
                "node_types": sorted({n.type for n in g.nodes.values()}),
                "predicates": sorted({e.predicate for e in g.edges}),
            }
            if t2p_cls is not None:
                info["text_to_prolog_module"] = getattr(
                    t2p_cls, "__module__", repr(t2p_cls))
            return info

        diag_btn.click(_diag, [graph_state, t2p_cls_state], [diag_json])

        return ui


# =====================================================================
# Запуск
# =====================================================================
def launch(share: bool = False, host: str = "127.0.0.1",
           port: int = 7860, inbrowser: bool = True, **kwargs) -> None:
    ui = build_ui()

    launch_kwargs: Dict[str, Any] = dict(
        share=share,
        server_name=host,
        server_port=port,
        inbrowser=inbrowser,
    )

    def _find_favicon() -> Optional[str]:
        here = os.path.dirname(os.path.abspath(__file__))
        for subdir in ("", "assets"):
            for name in ("favicon.png", "favicon.ico", "favicon.svg"):
                path = os.path.join(here, subdir, name) if subdir \
                    else os.path.join(here, name)
                if os.path.isfile(path):
                    return path
        return None

    _favicon = _find_favicon()
    if _favicon:
        launch_kwargs["favicon_path"] = _favicon
        print(f"[kg-editor] favicon: {_favicon}")
    else:
        _here = os.path.dirname(os.path.abspath(__file__))
        print(f"[kg-editor] favicon not found "
              f"(looked in: {_here}, {os.path.join(_here, 'assets')})")

    if _LAUNCH_THEME:
        launch_kwargs.update(
            theme=_make_theme(),
            css=_GLOBAL_CSS,
            head=_DARK_FORCE_HEAD,
        )
    launch_kwargs.update(kwargs)

    ui.launch(**launch_kwargs)


# =====================================================================
# CLI
# =====================================================================
def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="kg-editor",
        description="Knowledge Graph Editor (PyAgentProlog backend)",
    )
    parser.add_argument("--host", default="127.0.0.1",
                        help="Server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=7860,
                        help="Server port (default: 7860)")
    parser.add_argument("--share", action="store_true",
                        help="Publish via gradio.live")
    parser.add_argument("--no-browser", action="store_true",
                        help="Do not open the browser automatically")
    args = parser.parse_args(argv)

    launch(
        host=args.host,
        port=args.port,
        share=args.share,
        inbrowser=not args.no_browser,
    )


if __name__ == "__main__":
    main()