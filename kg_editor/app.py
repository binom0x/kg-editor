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
с классом TextToProlog. Поддерживается загрузка файлов (txt, pdf, docx, fb2)
с модальным окном для просмотра и редактирования полного текста.

v5.11.14 (app):
    * FIX: Безопасное редактирование ID узла (без потери данных при ошибке валидации).
    * FIX: Перехват ошибок валидации при редактировании/добавлении рёбер.
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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import gradio as gr

# ---------------------------------------------------------------------
# Безопасное определение версии Gradio
# ---------------------------------------------------------------------
try:
    _GRADIO_VERSION = tuple(int(x) for x in gr.__version__.split('.')[:2])
except ValueError:
    _GRADIO_VERSION = (4, 0)

_LAUNCH_THEME = _GRADIO_VERSION >= (6, 0)

# ---------------------------------------------------------------------
# Импорты локальных модулей
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
# NL-импорт (опционально)
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

try:
    from .dialog import DialogTurn, apply_facts_to_graph
except ImportError:
    from dialog import DialogTurn, apply_facts_to_graph

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

    window.toggleGraphFullscreen = function (btn) {
        var wrap = btn.closest('.pyvis-wrap');
        if (!wrap) return;
        var isFs = wrap.classList.toggle('graph-fullscreen');
        btn.innerHTML = isFs ? '✕' : '⛶';
        btn.title = isFs ? 'Свернуть' : 'Развернуть на весь экран';
        var iframe = wrap.querySelector('iframe');
        if (iframe && iframe.contentWindow) {
            setTimeout(function () {
                try {
                    var Ev = iframe.contentWindow.Event || Event;
                    iframe.contentWindow.dispatchEvent(new Ev('resize'));
                } catch (e) {}
            }, 150);
        }
    };

    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        document.querySelectorAll('.graph-fullscreen').forEach(function (wrap) {
            var btn = wrap.querySelector('.graph-fs-btn');
            if (btn) window.toggleGraphFullscreen(btn);
        });
    });
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

/* Hover-эффект для строк Dataframe */
.compact-table tr:hover td {
    background: #161a20 !important;
    cursor: pointer;
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

/* ---------- Fullscreen PyVis ---------- */
.pyvis-wrap { position: relative; }
.graph-fullscreen {
    position: fixed !important;
    top: 0 !important;
    left: 0 !important;
    width: 100vw !important;
    height: 100vh !important;
    z-index: 99999 !important;
    border: none !important;
    border-radius: 0 !important;
    aspect-ratio: auto !important;
    max-height: none !important;
    min-height: none !important;
}
.graph-fs-btn {
    position: absolute; top: 8px; left: 8px; z-index: 10;
    background: #21262d; color: #c7cbd1; border: 1px solid #3a4250;
    border-radius: 4px; cursor: pointer; padding: 4px 8px;
    font-size: 16px; line-height: 1; transition: background 0.15s, color 0.15s;
}
.graph-fs-btn:hover { background: #30363d; color: #ffffff; }

/* ---------- Modal Overlay ---------- */
.modal-overlay {
    position: fixed !important;
    top: 0 !important;
    left: 0 !important;
    width: 100vw !important;
    height: 100vh !important;
    background: rgba(11, 13, 17, 0.85) !important;
    z-index: 10000 !important;
    align-items: center !important;
    justify-content: center !important;
    backdrop-filter: blur(4px);
}
.modal-content {
    background: #161a20 !important;
    border: 1px solid #3a4250 !important;
    border-radius: 8px !important;
    padding: 20px !important;
    width: 85vw !important;
    max-width: 1400px !important;
    max-height: 90vh !important;
    display: flex !important;
    flex-direction: column !important;
    box-shadow: 0 10px 30px rgba(0,0,0,0.8) !important;
}
.modal-textarea textarea {
    min-height: 55vh !important;
    font-family: ui-monospace, monospace !important;
    font-size: 13px !important;
    background: #0b0d11 !important;
    color: #c7cbd1 !important;
    line-height: 1.5 !important;
}

/* ---------- Compact File Upload ---------- */
.compact-file { min-height: 60px !important; }
.compact-file .file-preview {
    background: #0b0d11 !important;
    border: 1px dashed #3a4250 !important;
    color: #8b949e !important;
    font-size: 12px !important;
}
.compact-file .file-preview:hover {
    border-color: #58a6ff !important;
    background: #161a20 !important;
}

/* Принудительный ряд для кнопок */
.nowrap-row {
    flex-wrap: nowrap !important;
    gap: 4px !important;
    display: flex !important;
    align-items: center !important;
}
.nowrap-row > div {
    flex: 1 1 auto !important;
    min-width: 0 !important;
}
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
# Данные для таблиц (списки списков с HTML)
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


def _nodes_data(g: KnowledgeGraph) -> List[List[str]]:
    deg: Dict[str, int] = {n: 0 for n in g.nodes}
    for e in g.edges:
        if e.source in deg:
            deg[e.source] += 1
        if e.target in deg:
            deg[e.target] += 1
    
    rows = []
    for n in g.nodes.values():
        color = _node_type_color(n.type)
        # Создаём HTML-чип для типа
        type_html = f'<span style="background-color:{color}22; color:{color}; padding:2px 6px; border-radius:4px; border:1px solid {color}66;">{n.type}</span>'
        rows.append([n.id, type_html, str(deg[n.id])])
    return rows


def _edges_data(g: KnowledgeGraph) -> List[List[str]]:
    rows = []
    for i, e in enumerate(g.edges):
        src_color = _node_type_color(g.nodes[e.source].type) if e.source in g.nodes else "#8b949e"
        tgt_color = _node_type_color(g.nodes[e.target].type) if e.target in g.nodes else "#8b949e"
        
        src_html = f'<span style="background-color:{src_color}22; color:{src_color}; padding:2px 6px; border-radius:4px; border:1px solid {src_color}66;">{e.source}</span>'
        tgt_html = f'<span style="background-color:{tgt_color}22; color:{tgt_color}; padding:2px 6px; border-radius:4px; border:1px solid {tgt_color}66;">{e.target}</span>'
        pred_html = f'<span style="color:#ff7b72; font-family:monospace;">─[{e.predicate}]→</span>'
        
        rows.append([str(i), src_html, pred_html, tgt_html])
    return rows


# =====================================================================
# Цветные чипы (для HTML-таблиц атрибутов и фильтров)
# =====================================================================
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


def _filtered_html(items: List[Tuple[str, str]]) -> str:
    if not items:
        return _empty_table_html(
            "Ничего не отфильтровано (или логирование выключено).\n"
            "Включите «🛡️ Логировать отфильтрованное» в блоке импорта НЛ.")
    rows: List[str] = []
    for atom, reason in items:
        rows.append(
            "<tr>"
            f'<td style="padding:4px 10px;border-bottom:1px solid #161a20;'
            f'font-family:ui-monospace,monospace;color:#ff7b72;'
            f'vertical-align:top;">'
            f'{_esc(atom)}</td>'
            f'<td style="padding:4px 10px;border-bottom:1px solid #161a20;'
            f'color:#8b949e;font-family:ui-sans-serif,system-ui,sans-serif;'
            f'font-size:11px;">'
            f'{_esc(reason)}</td>'
            "</tr>"
        )
    return _table_wrap(["терм / атом", "причина фильтрации"], rows,
                       align=["left", "left"])


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
        if g[0] or g[1]:
            parts.append(f'<span style="color:#7ee787;font-style:italic;">'
                         f'{_esc(raw)}</span>')
        elif g[2] or g[3]:
            parts.append(f'<span style="color:#ffa657;">{_esc(raw)}</span>')
        elif g[4]:
            parts.append(f'<span style="color:#ff7b72;font-weight:600;">'
                         f'{_esc(raw)}</span>')
        elif g[5]:
            parts.append(f'<span style="color:#8b949e;">{_esc(raw)}</span>')
        elif g[6]:
            parts.append(f'<span style="color:#ff7b72;font-weight:600;">'
                         f'!</span>')
        elif g[7]:
            parts.append(f'<span style="color:#ff7b72;">{_esc(raw)}</span>')
        elif g[8]:
            parts.append(f'<span style="color:#ff7b72;">{_esc(raw)}</span>')
        elif g[9]:
            parts.append(f'<span style="color:#79c0ff;">{_esc(raw)}</span>')
        elif g[10]:
            parts.append(f'<span style="color:#d2a8ff;">{_esc(raw)}</span>')
        elif g[11]:
            parts.append(f'<span style="color:#c7cbd1;">{_esc(raw)}</span>')
        elif g[12]:
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
        _nodes_data(g),
        _edges_data(g),
        _attrs_html(g),
        _stats_html(g),
        render_pyvis(g),
    )


def _serialize_and_preview(g):
    src = g.to_prolog() if isinstance(g, KnowledgeGraph) else ""
    return src, _prolog_code_html(src)


# ---- Диалоги выбора файлов -------------------------------------------
def _pick_file(initial: str = "", title: str = "Выберите файл",
               save: bool = False,
               filetypes: Optional[List[Tuple[str, str]]] = None
               ) -> Optional[str]:
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
# Извлечение текста из файлов
# =====================================================================
def extract_text_from_file(file_path: str) -> Optional[str]:
    ext = Path(file_path).suffix.lower()
    try:
        if ext == '.txt':
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        elif ext == '.fb2':
            import xml.etree.ElementTree as ET
            tree = ET.parse(file_path)
            root = tree.getroot()
            ns = {'fb': 'http://www.gribuser.ru/xml/fictionbook/2.0'}
            text_parts = []
            for section in root.findall('.//fb:section', ns):
                for p in section.findall('.//fb:p', ns):
                    if p.text:
                        text_parts.append(p.text)
            return '\n'.join(text_parts)
        elif ext == '.pdf':
            try:
                import PyPDF2
                with open(file_path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    return '\n'.join([page.extract_text() for page in reader.pages if page.extract_text()])
            except ImportError:
                return "❌ Для чтения PDF установите: pip install PyPDF2"
        elif ext == '.docx':
            try:
                import docx
                doc = docx.Document(file_path)
                return '\n'.join([p.text for p in doc.paragraphs])
            except ImportError:
                return "❌ Для чтения DOCX установите: pip install python-docx"
        else:
            return f"❌ Неподдерживаемый формат: {ext}"
    except Exception as e:
        return f"❌ Ошибка чтения файла: {e}"


def h_load_text_file(file):
    if file is None:
        return "", _status_html("Файл не выбран"), gr.update(visible=False), gr.update(visible=False)
    path = file.name if hasattr(file, "name") else str(file)
    text = extract_text_from_file(path)
    if not text:
        return "", _status_html(f"❌ Не удалось прочитать файл: {path}"), gr.update(visible=False), gr.update(visible=False)
    if text.startswith("❌"):
        return "", _status_html(text), gr.update(visible=False), gr.update(visible=False)
    return (
        text,
        _status_html(f"✅ Файл загружен ({len(text)} символов). Нажмите «📝 Открыть текст», чтобы просмотреть и отредактировать."),
        gr.update(visible=True),
        gr.update(visible=False)
    )


def h_open_modal(state_text):
    if not state_text:
        return gr.update(visible=False), ""
    return gr.update(visible=True), state_text


def h_apply_modal(modal_text_val):
    return gr.update(visible=False), modal_text_val, _status_html("✅ Текст обновлён.")


def h_clear_nl():
    return "", "", _status_html("Очищено."), gr.update(visible=False), gr.update(visible=False)


# =====================================================================
# Загрузка пользовательского TextToProlog
# =====================================================================
def _h_pick_t2p() -> str:
    p = _pick_file(
        title="Выберите модуль text-to-prolog (.py)",
        filetypes=[("Python (*.py)", "*.py"), ("All files", "*.*")],
    )
    return p or ""


def h_load_t2p_module(path: str):
    path = (path or "").strip()
    if not path:
        return None, _status_html("✗ Укажите путь к .py-файлу")
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return None, _status_html(f"✗ Файл не найден: {path}")
    if not path.endswith(".py"):
        return None, _status_html(f"✗ Ожидался .py-файл, получено: {path}")

    mod_dir = os.path.dirname(path)
    if mod_dir and mod_dir not in _sys.path:
        _sys.path.insert(0, mod_dir)

    unique_name = f"_kg_editor_custom_t2p_{_uuid.uuid4().hex[:8]}"
    try:
        spec = importlib.util.spec_from_file_location(unique_name, path)
        if spec is None or spec.loader is None:
            return None, _status_html(f"✗ Не удалось создать загрузчик для: {path}")
        module = importlib.util.module_from_spec(spec)
        _sys.modules[unique_name] = module
        spec.loader.exec_module(module)
    except Exception as e:
        _sys.modules.pop(unique_name, None)
        return None, _status_html(f"✗ Ошибка импорта {path}:\n{e}\n\n{traceback.format_exc()}")

    if not hasattr(module, "TextToProlog"):
        _sys.modules.pop(unique_name, None)
        return None, _status_html(f"✗ В модуле нет класса TextToProlog: {path}")

    cls = module.TextToProlog
    if not hasattr(cls, 'parse') and not hasattr(cls, 'convert'):
        _sys.modules.pop(unique_name, None)
        return None, _status_html(f"✗ Класс TextToProlog не имеет ни parse(), ни convert(): {path}")

    try:
        cls()
    except Exception as e:
        _sys.modules.pop(unique_name, None)
        return None, _status_html(f"✗ Класс TextToProlog не инициализируется без аргументов:\n{e}")

    return cls, _status_html(f"✓ Загружен модуль: {path}\n  класс: TextToProlog\n  as sys.modules['{unique_name}']")


# =====================================================================
# Handlers — CRUD и выбор
# =====================================================================
def h_add_node(g, nid, ntype):
    g = _safe(g)
    try:
        g.add_node(nid, ntype or "concept")
        return (*_refresh(g), "", "")
    except Exception as e:
        return (*_refresh(g), "", f"✗ {e}")


def h_select_node(evt: gr.SelectData, g):
    g = _safe(g)
    row = evt.index[0]
    if 0 <= row < len(g.nodes):
        node_id = list(g.nodes.keys())[row]
        n = g.nodes[node_id]
        return n.id, n.type, node_id
    return "", "", ""


def h_edit_node(g, old_id, new_id, new_type):
    g = _safe(g)
    if not old_id:
        return (*_refresh(g), "✗ Кликните по строке в таблице")
    if old_id not in g.nodes:
        return (*_refresh(g), "✗ Узел не найден")
    
    old_node = g.nodes[old_id]
    final_id = new_id.strip() if new_id and new_id.strip() else old_id
    final_type = new_type.strip() if new_type and new_type.strip() else old_node.type
    
    if final_id != old_id:
        if final_id in g.nodes:
            return (*_refresh(g), f"✗ Узел '{final_id}' уже существует")
        
        props = old_node.props
        # Безопасное создание: пробуем создать новый узел, чтобы проверить валидность ID
        try:
            g.add_node(final_id, final_type, props)
        except Exception as e:
            return (*_refresh(g), f"✗ Ошибка переименования: {e}")
            
        # Если создание прошло успешно, обновляем связи
        for e in g.edges:
            if e.source == old_id: e.source = final_id
            if e.target == old_id: e.target = final_id
        
        for a in g.attributes:
            if a.entity == old_id: a.entity = final_id
            
        # Теперь безопасно удаляем старый узел (его связи уже перенаправлены)
        g.remove_node(old_id)
    else:
        # Просто меняем тип
        try:
            g.add_node(old_id, final_type)
        except Exception as e:
            return (*_refresh(g), f"✗ Ошибка: {e}")
        
    return (*_refresh(g), f"✓ Узел обновлён: {final_id}")


def h_del_node_selected(g, selected_id):
    g = _safe(g)
    if not selected_id:
        return (*_refresh(g), "✗ Кликните по строке в таблице")
    if g.remove_node(selected_id):
        return (*_refresh(g), f"✓ Узел {selected_id} удалён")
    return (*_refresh(g), "✗ Узел не найден")


def h_add_edge(g, src, tgt, pred):
    g = _safe(g)
    try:
        g.add_edge(src, tgt, pred)
        return (*_refresh(g), "", "", "")
    except Exception as e:
        return (*_refresh(g), "", "", f"✗ {e}")


def h_select_edge(evt: gr.SelectData, g):
    g = _safe(g)
    row = evt.index[0]
    if 0 <= row < len(g.edges):
        e = g.edges[row]
        return e.source, e.target, e.predicate, str(row)
    return "", "", "", ""


def h_edit_edge(g, idx_str, new_src, new_tgt, new_pred):
    g = _safe(g)
    if not idx_str:
        return (*_refresh(g), "✗ Кликните по строке в таблице")
    try:
        idx = int(idx_str)
        if not (0 <= idx < len(g.edges)):
            return (*_refresh(g), "✗ Ребро не найдено")
        
        old_edge = g.edges[idx]
        final_src = new_src.strip() if new_src and new_src.strip() else old_edge.source
        final_tgt = new_tgt.strip() if new_tgt and new_tgt.strip() else old_edge.target
        final_pred = new_pred.strip() if new_pred and new_pred.strip() else old_edge.predicate
        
        # Безопасное создание узлов, если их нет
        try:
            if final_src not in g.nodes: g.add_node(final_src)
            if final_tgt not in g.nodes: g.add_node(final_tgt)
        except Exception as e:
            return (*_refresh(g), f"✗ Ошибка добавления узла: {e}")
        
        old_edge.source = final_src
        old_edge.target = final_tgt
        old_edge.predicate = final_pred
        
        return (*_refresh(g), f"✓ Ребро обновлено: {final_src} -> {final_tgt}")
    except Exception as e:
        return (*_refresh(g), f"✗ {e}")


def h_del_edge_selected(g, idx_str):
    g = _safe(g)
    if not idx_str:
        return (*_refresh(g), "✗ Кликните по строке в таблице")
    try:
        idx = int(idx_str)
        if g.remove_edge(idx):
            return (*_refresh(g), "✓ Ребро удалено")
    except Exception:
        pass
    return (*_refresh(g), "✗ Ребро не найдено")


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
# Handlers — импорт
# =====================================================================
def h_import_full_graph(g, short_text, full_text, t2p_cls=None, log_filtered=False):
    g = _safe(g)
    cls = t2p_cls if t2p_cls is not None else (TextToProlog if _T2P_OK else None)
    if cls is None:
        return _status_html("✗ text_to_prolog недоступен."), g, _filtered_html([])
    text = (full_text or "").strip() or (short_text or "").strip()
    if not text:
        return _status_html("✗ Пустой текст"), g, _filtered_html([])
    
    try:
        t2p = cls()
        kwargs = {'strict': True, 'facts_from_questions': True}
        if log_filtered: kwargs['log_filtered'] = True
        
        try:
            facts_src, _ = t2p.parse(text, **kwargs)
        except TypeError:
            kwargs.pop('facts_from_questions', None)
            kwargs.pop('log_filtered', None)
            facts_src, _ = t2p.parse(text, **kwargs)
            
        filtered_items = list(getattr(t2p, 'filtered_atoms', []) or []) if log_filtered else []
        
        new_g = KnowledgeGraph.from_prolog(facts_src or "")
        for n in new_g.nodes.values(): g.add_node(n.id, n.type, n.props)
        for e in new_g.edges: g.add_edge(e.source, e.target, e.predicate)
        for a in new_g.attributes: g.add_attribute(a.entity, a.name, a.value)

        msg = (f"✓ Факты: +{len(new_g.nodes)} узлов, "
               f"+{len(new_g.edges)} рёбер, +{len(new_g.attributes)} атрибутов")
        return _status_html(msg), g, _filtered_html(filtered_items)
    except Exception as e:
        return _status_html(f"✗ {e}"), g, _filtered_html([])


def h_extract_query(short_text, full_text, t2p_cls=None):
    cls = t2p_cls if t2p_cls is not None else (TextToProlog if _T2P_OK else None)
    if cls is None:
        return "", _status_html("✗ text_to_prolog недоступен.")
    text = (full_text or "").strip() or (short_text or "").strip()
    if not text:
        return "", _status_html("✗ Пустой текст")

    try:
        t2p = cls()
        try:
            _, query_src = t2p.parse(text, strict=True, facts_from_questions=False)
        except TypeError:
            _, query_src = t2p.parse(text, strict=True)

        if not query_src:
            return "", _status_html("ℹ️ Вопросов не найдено.")
        return query_src, _status_html(f"✓ Извлечён запрос:\n{query_src[:100]}...")
    except Exception as e:
        return "", _status_html(f"✗ {e}")


def h_parse_source(g, code):
    try:
        new_g = KnowledgeGraph.from_prolog(code or "")
        return _refresh(new_g)[0], _status_html("✓ Разобрано")
    except Exception as e:
        return g, _status_html(f"✗ {e}")


def h_open_file(g):
    p = _pick_file(title="Открыть .pl графа")
    if not p:
        return _refresh(_safe(g)) + (_status_html("Файл не выбран"),)
    try:
        with open(p, encoding="utf-8") as f:
            new_g = KnowledgeGraph.from_prolog(f.read())
        return _refresh(new_g) + (_status_html(f"✓ Загружено: {p}"),)
    except Exception as e:
        return _refresh(_safe(g)) + (_status_html(f"✗ {e}"),)


def h_save_file(g, current_path):
    g = _safe(g)
    p = current_path or _pick_file(title="Сохранить как...", save=True)
    if not p: return _status_html("✗ Не выбран файл"), current_path
    try:
        with open(p, "w", encoding="utf-8") as f: f.write(g.to_prolog())
        return _status_html(f"✓ Сохранено: {p}"), p
    except Exception as e:
        return _status_html(f"✗ {e}"), current_path


def h_new_project(g):
    p = _pick_folder(title="Папка нового проекта")
    if not p: return _refresh(_safe(g)) + (_status_html("Отменено"),)
    try:
        os.makedirs(p, exist_ok=True)
        kb = os.path.join(p, "graph.pl")
        if not os.path.isfile(kb):
            with open(kb, "w", encoding="utf-8") as f: f.write("% Graph\n")
        new_g = KnowledgeGraph.from_prolog(open(kb, encoding="utf-8").read())
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
    return _refresh(demo) + (_status_html("✓ Демо-граф"),)


# =====================================================================
# Запросы
# =====================================================================
def h_query(g, text):
    g = _safe(g)
    text = (text or "").strip()
    if not text: return {"result": None}, "✗ Пустой запрос"
    if not _AGENT_OK: return {"error": "PyAgentProlog недоступен"}, "✗ Установите prolog"

    q = text if text.endswith(".") else text + "."
    try:
        src = _graph_to_program(g)
        agent = Agent(src, context={})
    except Exception as e:
        return {"error": str(e)}, f"✗ Ошибка агента: {e}"

    sols, truncated = [], False
    try:
        for item in agent.stream(q):
            if isinstance(item, dict) and 'error' in item: return {"error": item['error']}, f"✗ {item['error']}"
            if item is False: return {"result": False}, "✗ Нет решений"
            if item is True: return {"result": True}, "✓ true"
            if isinstance(item, dict): sols.append(item)
            if len(sols) >= _SOLUTION_LIMIT: truncated = True; break
    except Exception as e:
        return {"error": str(e)}, f"✗ {e}"

    if not sols: return {"result": None}, "Нет решений"
    return sols, f"✓ {len(sols)} решение(й)"


def h_dialog_ask(g, text, dlg_state): return {"result": "Диалог отключен в этой версии"}, "✗ Функция в разработке", dlg_state
def h_dialog_answer(g, text, dlg_state): return g, "✗ Функция в разработке", "", dlg_state, {}
def h_dialog_yes(g, dlg_state): return g, "✗ Функция в разработке", "", dlg_state, {}
def h_dialog_no(g, dlg_state): return g, "✗ Функция в разработке", "", dlg_state, {}
def h_dialog_transcript(dlg_state): return "✗ Функция в разработке"


# =====================================================================
# UI
# =====================================================================
def build_ui() -> gr.Blocks:
    _blocks_kwargs = {"title": "KnowledgeGraph Editor"}
    if not _LAUNCH_THEME:
        _blocks_kwargs.update(css=_GLOBAL_CSS, theme=_make_theme(), head=_DARK_FORCE_HEAD)

    with gr.Blocks(**_blocks_kwargs) as ui:
        graph_state = gr.State(KnowledgeGraph())
        current_path = gr.State("")
        t2p_cls_state = gr.State(None)
        nl_text_state = gr.State("")
        
        sel_node_id = gr.State("")
        sel_edge_idx = gr.State("")

        with gr.Row(equal_height=False):
            # КОЛОНКА 1
            with gr.Column(scale=2, min_width=300):
                gr.HTML('<div class="col-head">📁 Граф / Проект</div>')
                with gr.Row(equal_height=True):
                    open_btn = gr.Button("📂 Открыть", size="sm", elem_classes=["compact-btn"])
                    new_btn = gr.Button("🆕 Создать", size="sm", elem_classes=["compact-btn"])
                    save_btn = gr.Button("💾 Сохранить", size="sm", elem_classes=["compact-btn"])
                    example_btn = gr.Button("📚", size="sm", scale=0, elem_classes=["compact-btn"])

                stats_html = gr.HTML(_stats_html(KnowledgeGraph()))

                with gr.Accordion("📝 Импорт из НЛ", open=False):
                    text_file_input = gr.File(label="Файл (txt, pdf, docx, fb2)", file_types=[".txt", ".pdf", ".docx", ".fb2"], elem_classes=["compact-file"])
                    file_status = gr.HTML("")
                    open_modal_btn = gr.Button("📝 Открыть текст", size="sm", visible=False, elem_classes=["compact-btn"])

                    nl_text = gr.Textbox(label="Краткий текст", lines=3, elem_classes=["compact-tb"])
                    with gr.Row(equal_height=True, elem_classes=["nowrap-row"]):
                        btn_full_graph = gr.Button("📊 Факты", size="sm", scale=1, min_width=0, elem_classes=["compact-btn"], variant="primary")
                        btn_extract_query = gr.Button("❓ Запрос", size="sm", scale=1, min_width=0, elem_classes=["compact-btn"])
                        clear_text_btn = gr.Button("🗑️", size="sm", scale=0, min_width=0, elem_classes=["compact-btn"])
                        
                    log_filtered_cb = gr.Checkbox(label="🛡️ Логировать отфильтрованное", value=True)
                    nl_status = gr.HTML(_status_html("Готов."))

                    with gr.Accordion("⚙️ Пользовательский конвертер", open=False):
                        t2p_path_in = gr.Textbox(placeholder="Путь к .py-файлу", show_label=False, lines=1, elem_classes=["compact-tb"])
                        with gr.Row(equal_height=True):
                            t2p_pick_btn = gr.Button("📂 Выбрать", size="sm", elem_classes=["compact-btn"])
                            t2p_load_btn = gr.Button("✅ Загрузить", size="sm", elem_classes=["compact-btn"])
                            t2p_reset_btn = gr.Button("↺ Встроенный", size="sm", elem_classes=["compact-btn"])
                        t2p_status = gr.HTML(_status_html("Встроенный" if _T2P_OK else "Недоступен"))

                with gr.Accordion("📥 Импорт из Prolog", open=False):
                    import_code = gr.Code(language=None, lines=8, value="% Вставьте Prolog-код")
                    import_btn = gr.Button("📥 Разобрать", size="sm", elem_classes=["compact-btn"])
                    import_status = gr.HTML(_status_html("Готов."))

                with gr.Accordion("🔬 Диагностика", open=False):
                    diag_btn = gr.Button("🔄 Показать", size="sm", elem_classes=["compact-btn"])
                    diag_json = gr.JSON(label="", show_label=False)

            # КОЛОНКА 2
            with gr.Column(scale=5, min_width=500):
                gr.HTML('<div class="col-head">🧩 Редактор графа</div>')

                with gr.Tabs():
                    with gr.Tab("Узлы"):
                        nodes_tbl = gr.Dataframe(
                            headers=["id", "type", "degree"],
                            datatype=["str", "html", "str"],
                            type="array",
                            interactive=False,
                            wrap=True,
                            elem_classes=["compact-table"]
                        )
                        with gr.Row(equal_height=True):
                            nid_in = gr.Textbox(placeholder="id (apple)", show_label=False, scale=2, elem_classes=["compact-tb"])
                            ntype_in = gr.Textbox(placeholder="type (org, person...)", show_label=False, scale=2, elem_classes=["compact-tb"])
                            add_node_btn = gr.Button("➕", size="sm", scale=1, min_width=0, elem_classes=["compact-btn"])
                        
                        with gr.Row(equal_height=True):
                            edit_node_id_in = gr.Textbox(placeholder="ID", show_label=False, scale=2, elem_classes=["compact-tb"])
                            edit_node_type_in = gr.Textbox(placeholder="Type", show_label=False, scale=2, elem_classes=["compact-tb"])
                            edit_node_btn = gr.Button("💾", size="sm", scale=1, min_width=0, elem_classes=["compact-btn"])
                            del_node_btn = gr.Button("🗑️", size="sm", scale=1, min_width=0, elem_classes=["compact-btn"])
                        
                        node_msg = gr.Textbox(label="", show_label=False, interactive=False, lines=1, elem_classes=["compact-tb"])

                    with gr.Tab("Рёбра"):
                        edges_tbl = gr.Dataframe(
                            headers=["idx", "source", "predicate", "target"],
                            datatype=["str", "html", "html", "html"],
                            type="array",
                            interactive=False,
                            wrap=True,
                            elem_classes=["compact-table"]
                        )
                        with gr.Row(equal_height=True):
                            esrc_in = gr.Textbox(placeholder="source", show_label=False, scale=2, elem_classes=["compact-tb"])
                            etgt_in = gr.Textbox(placeholder="target", show_label=False, scale=2, elem_classes=["compact-tb"])
                            epred_in = gr.Textbox(placeholder="predicate", show_label=False, scale=2, elem_classes=["compact-tb"])
                            add_edge_btn = gr.Button("➕", size="sm", scale=1, min_width=0, elem_classes=["compact-btn"])

                        with gr.Row(equal_height=True):
                            edit_edge_src_in = gr.Textbox(placeholder="Source", show_label=False, scale=2, elem_classes=["compact-tb"])
                            edit_edge_tgt_in = gr.Textbox(placeholder="Target", show_label=False, scale=2, elem_classes=["compact-tb"])
                            edit_edge_pred_in = gr.Textbox(placeholder="Predicate", show_label=False, scale=2, elem_classes=["compact-tb"])
                            edit_edge_btn = gr.Button("💾", size="sm", scale=1, min_width=0, elem_classes=["compact-btn"])
                            del_edge_btn = gr.Button("🗑️", size="sm", scale=1, min_width=0, elem_classes=["compact-btn"])

                        edge_msg = gr.Textbox(label="", show_label=False, interactive=False, lines=1, elem_classes=["compact-tb"])

                    with gr.Tab("Атрибуты"):
                        attrs_tbl = gr.HTML(_attrs_html(KnowledgeGraph()))
                        with gr.Row(equal_height=True):
                            aent_in = gr.Textbox(placeholder="entity", show_label=False, scale=2, elem_classes=["compact-tb"])
                            aname_in = gr.Textbox(placeholder="name", show_label=False, scale=2, elem_classes=["compact-tb"])
                            aval_in = gr.Textbox(placeholder="value", show_label=False, scale=2, elem_classes=["compact-tb"])
                            add_attr_btn = gr.Button("➕", size="sm", scale=1, min_width=0, elem_classes=["compact-btn"])
                        with gr.Row(equal_height=True):
                            del_attr_dd = gr.Dropdown(choices=[], label="Удалить", show_label=False, scale=4)
                            del_attr_btn = gr.Button("🗑️", size="sm", scale=1, min_width=0, elem_classes=["compact-btn"])
                        attr_msg = gr.Textbox(label="", show_label=False, interactive=False, lines=1, elem_classes=["compact-tb"])

                    with gr.Tab("🛡️ Отфильтровано"):
                        filtered_tbl = gr.HTML(_empty_table_html("Нет данных. Включите логирование."))

                    with gr.Tab("Prolog source"):
                        src_preview = gr.HTML(_prolog_code_html(""))
                        with gr.Accordion("✏️ Редактировать", open=False):
                            src_code = gr.Code(language=None, lines=18, value="% Нажмите 🔄")
                        with gr.Row(equal_height=True):
                            serialize_btn = gr.Button("🔄 Обновить из графа", size="sm", elem_classes=["compact-btn"])
                            parse_src_btn = gr.Button("📥 Применить", size="sm", elem_classes=["compact-btn"])
                        src_status = gr.HTML(_status_html("Готов."))

            # КОЛОНКА 3
            with gr.Column(scale=4, min_width=420):
                gr.HTML('<div class="col-head">🖼️ Визуализация (PyVis)</div>')
                graph_html = gr.HTML(render_pyvis(None))

                gr.HTML('<div class="col-head">🔎 Запросы</div>')
                query_in = gr.Textbox(placeholder="edge(X, Y, owns).", lines=3, show_label=False, elem_classes=["compact-tb"])
                with gr.Row(equal_height=True):
                    run_q_btn = gr.Button("▶ Запрос", size="sm", elem_classes=["compact-btn"])
                    help_btn = gr.Button("ℹ️ Помощь", size="sm", elem_classes=["compact-btn"])

                query_status = gr.Textbox(label="", show_label=False, interactive=False, lines=1, elem_classes=["compact-tb"])
                query_out = gr.JSON(label="Решения", show_label=False)

                if not _AGENT_OK:
                    gr.Markdown(f"⚠️ PyAgentProlog не загружен")

        # Модальное окно
        with gr.Column(visible=False, elem_classes=["modal-overlay"]) as modal_col:
            with gr.Column(elem_classes=["modal-content"]):
                gr.HTML('<div class="col-head">📄 Текст</div>')
                modal_text = gr.Textbox(lines=20, show_label=False, elem_classes=["modal-textarea"])
                with gr.Row():
                    modal_apply_btn = gr.Button("✅ Применить", size="sm", variant="primary")
                    modal_cancel_btn = gr.Button("❌ Отмена", size="sm")

        # =================================================================
        # Wiring
        # =================================================================
        refresh_outs = [
            graph_state, nodes_tbl, edges_tbl, attrs_tbl,
            stats_html, graph_html
        ]

        # Настройки
        t2p_pick_btn.click(_h_pick_t2p, [], [t2p_path_in])
        t2p_load_btn.click(h_load_t2p_module, [t2p_path_in], [t2p_cls_state, t2p_status])
        t2p_reset_btn.click(lambda: (None, _status_html("↺ Сброшено")), [], [t2p_cls_state, t2p_status])

        # Импорт НЛ
        text_file_input.upload(h_load_text_file, [text_file_input], [nl_text_state, file_status, open_modal_btn, modal_col])
        open_modal_btn.click(h_open_modal, [nl_text_state], [modal_col, modal_text])
        modal_apply_btn.click(h_apply_modal, [modal_text], [modal_col, nl_text_state, file_status])
        modal_cancel_btn.click(lambda: gr.update(visible=False), [], [modal_col])
        clear_text_btn.click(h_clear_nl, [], [nl_text, nl_text_state, file_status, open_modal_btn, modal_col])

        btn_full_graph.click(
            h_import_full_graph,
            [graph_state, nl_text, nl_text_state, t2p_cls_state, log_filtered_cb],
            [nl_status, graph_state, filtered_tbl],
        ).then(lambda g: _refresh(g), [graph_state], refresh_outs)

        btn_extract_query.click(h_extract_query, [nl_text, nl_text_state, t2p_cls_state], [query_in, nl_status])
        import_btn.click(h_parse_source, [graph_state, import_code], [graph_state, src_status]).then(lambda g: _refresh(g), [graph_state], refresh_outs)

        # Проект
        open_btn.click(h_open_file, [graph_state], refresh_outs + [import_status]).then(_serialize_and_preview, [graph_state], [src_code, src_preview])
        new_btn.click(h_new_project, [graph_state], refresh_outs + [import_status]).then(_serialize_and_preview, [graph_state], [src_code, src_preview])
        example_btn.click(h_load_example, [graph_state], refresh_outs + [import_status]).then(_serialize_and_preview, [graph_state], [src_code, src_preview])
        save_btn.click(h_save_file, [graph_state, current_path], [import_status, current_path])

        # Узлы: Добавление и выбор
        add_node_btn.click(h_add_node, [graph_state, nid_in, ntype_in], refresh_outs + [nid_in, node_msg])
        
        nodes_tbl.select(
            h_select_node,
            [graph_state],
            [edit_node_id_in, edit_node_type_in, sel_node_id]
        )
        
        edit_node_btn.click(
            h_edit_node,
            [graph_state, sel_node_id, edit_node_id_in, edit_node_type_in],
            refresh_outs + [node_msg]
        )
        
        del_node_btn.click(
            h_del_node_selected,
            [graph_state, sel_node_id],
            refresh_outs + [node_msg]
        )

        # Рёбра: Добавление и выбор
        add_edge_btn.click(h_add_edge, [graph_state, esrc_in, etgt_in, epred_in], refresh_outs + [esrc_in, etgt_in, edge_msg])
        
        edges_tbl.select(
            h_select_edge,
            [graph_state],
            [edit_edge_src_in, edit_edge_tgt_in, edit_edge_pred_in, sel_edge_idx]
        )
        
        edit_edge_btn.click(
            h_edit_edge,
            [graph_state, sel_edge_idx, edit_edge_src_in, edit_edge_tgt_in, edit_edge_pred_in],
            refresh_outs + [edge_msg]
        )
        
        del_edge_btn.click(
            h_del_edge_selected,
            [graph_state, sel_edge_idx],
            refresh_outs + [edge_msg]
        )

        # Атрибуты
        add_attr_btn.click(h_add_attr, [graph_state, aent_in, aname_in, aval_in], refresh_outs + [aent_in, aname_in, attr_msg])
        del_attr_btn.click(h_del_attr, [graph_state, del_attr_dd], refresh_outs)

        # Prolog Source
        serialize_btn.click(_serialize_and_preview, [graph_state], [src_code, src_preview])
        src_code.change(lambda s: _prolog_code_html(s or ""), [src_code], [src_preview])
        parse_src_btn.click(h_parse_source, [graph_state, src_code], [graph_state, src_status]).then(lambda g: _refresh(g), [graph_state], refresh_outs)

        # Запросы
        run_q_btn.click(h_query, [graph_state, query_in], [query_out, query_status])
        help_btn.click(lambda: _status_html("Доступно: edge/2,3 node/2,3 attribute/3 findall/3 и т.д."), [], [query_status])

        # Диагностика
        diag_btn.click(lambda g, c: {"summary": _safe(g).summary(), "pyagent": _AGENT_OK, "t2p": "custom" if c else _T2P_OK}, [graph_state, t2p_cls_state], [diag_json])

        return ui


def launch(share: bool = False, host: str = "127.0.0.1", port: int = 7860, inbrowser: bool = True, **kwargs) -> None:
    ui = build_ui()
    launch_kwargs = dict(share=share, server_name=host, server_port=port, inbrowser=inbrowser)
    
    _here = os.path.dirname(os.path.abspath(__file__))
    for subdir in ("", "assets"):
        for name in ("favicon.png", "favicon.ico", "favicon.svg"):
            path = os.path.join(_here, subdir, name) if subdir else os.path.join(_here, name)
            if os.path.isfile(path):
                launch_kwargs["favicon_path"] = path
                break

    if _LAUNCH_THEME:
        launch_kwargs.update(theme=_make_theme(), css=_GLOBAL_CSS, head=_DARK_FORCE_HEAD)
    launch_kwargs.update(kwargs)
    ui.launch(**launch_kwargs)


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--share", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    launch(host=args.host, port=args.port, share=args.share, inbrowser=not args.no_browser)


if __name__ == "__main__":
    main()