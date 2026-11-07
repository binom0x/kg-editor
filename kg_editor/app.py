"""KnowledgeGraph Editor — Gradio Blocks UI (PyAgentProlog backend).

Query engine — PyAgentProlog (prolog.agent.Agent).
Graph format is compatible with text_to_prolog._to_graph_program:

    node(Id, Props, Type).
    edge(Source, Target, Predicate).
    attribute(Entity, Name, Value).

On top of the facts, convenience rules are added automatically:

    node(Id, Type) :- node(Id, _, Type).
    edge(S, T) :- edge(S, T, _).

So queries may be written as:
    node(apple, X)
    edge(X, Y, owns)
    attribute(X, release_year, Y)
    \\+(node(X, person))
    findall(X, edge(apple, X, _), L)

Every query is built on a fresh agent — mutations via assertz/retract
only live within a single query and do not affect the graph model.

Editor: colored HTML tables + full Prolog syntax highlighting.
NL import: optional. The `nl2prolog` package is the default extractor
but NOT a hard dependency. Without it, the user may load a custom
.py module with a TextToProlog class. The editor core (graph, CRUD,
Prolog import/export, queries, PyVis) works independently.

i18n: English / Russian, switchable via KG_EDITOR_LANG env var
(same mechanism as the Fona dashboard: TRANSLATIONS table + t()).

v5.13:
    * FEAT: dialog mode ("💬 Dialog" tab).
      — ask/answer/yes/no/reset via DialogTurn.
      — facts from NL assertions are applied to the graph automatically.
      — pending question is shown in a dedicated panel.
      — dlg_state is reset on extractor switch or full graph replacement.

v5.12:
    * FIX: safe import of dialog.py — editor starts without nl2prolog.
    * FIX: extractor status banner (nl2prolog / user-provided).
    * FIX: when the extractor is missing, the "Custom converter"
      accordion is open by default.
    * FIX: informative messages in NL import handlers when the extractor
      is not set — with instructions to load a custom one or install
      nl2prolog.
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
# Safe Gradio version detection
# ---------------------------------------------------------------------
try:
    _GRADIO_VERSION = tuple(int(x) for x in gr.__version__.split('.')[:2])
except ValueError:
    _GRADIO_VERSION = (4, 0)

_LAUNCH_THEME = _GRADIO_VERSION >= (6, 0)

# ---------------------------------------------------------------------
# Local module imports
# ---------------------------------------------------------------------
try:
    from .graph_model import KnowledgeGraph
    from .graph_layout import render_pyvis
except ImportError:
    from graph_model import KnowledgeGraph
    from graph_layout import render_pyvis

# ---------------------------------------------------------------------
# PyAgentProlog (optional)
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
# NL import (optional) — shim onto nl2prolog or local
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

# ---------------------------------------------------------------------
# nl2prolog package — separate check for diagnostics
# ---------------------------------------------------------------------
try:
    import nl2prolog as _nl2prolog_module  # noqa: F401
    _NL2PROLOG_OK = True
    _NL2PROLOG_VERSION = getattr(_nl2prolog_module, "__version__", "?")
except ImportError:
    _NL2PROLOG_OK = False
    _NL2PROLOG_VERSION = None

# ---------------------------------------------------------------------
# Dialog — optional; the dialog mode needs DialogTurn.
# The import must be safe so kg-editor can start without nl2prolog.
# ---------------------------------------------------------------------
try:
    try:
        from .dialog import DialogTurn, apply_facts_to_graph
    except ImportError:
        from dialog import DialogTurn, apply_facts_to_graph
    _DIALOG_OK = True
except Exception:
    DialogTurn = None
    apply_facts_to_graph = None
    _DIALOG_OK = False


# =====================================================================
# i18n
# =====================================================================
TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en": {
        # generic
        "title": "KnowledgeGraph Editor",
        "lang_override_hint":
            "override with KG_EDITOR_LANG=en|ru",

        # column headers
        "col_project": "📁 Graph / Project",
        "col_editor": "🧩 Graph editor",
        "col_visual": "🖼️ Visualization (PyVis)",
        "col_queries": "🔎 Queries",

        # project buttons
        "btn_open": "📂 Open",
        "btn_merge": "🔀 Merge",
        "btn_new": "🆕 Create",
        "btn_save": "💾 Save",
        "btn_example": "📚",

        # stats
        "stats_nodes": "Nodes:",
        "stats_edges": "Edges:",
        "stats_attrs": "Attributes:",

        # NL import accordion
        "nl_import_title": "📝 Import from NL",
        "nl_file_label": "File (txt, pdf, docx, fb2)",
        "nl_open_text_btn": "📝 Open text",
        "nl_short_text_label": "Short text",
        "nl_btn_facts": "📊 Facts",
        "nl_btn_query": "❓ Query",
        "nl_btn_clear": "🗑️",
        "nl_log_filtered": "🛡️ Log filtered",
        "nl_status_ready": "Ready.",
        "custom_conv_title": "⚙️ Custom converter",
        "t2p_path_placeholder": "Path to .py file",
        "t2p_pick": "📂 Choose",
        "t2p_load": "✅ Load",
        "t2p_reset": "↺ Built-in",
        "t2p_status_builtin": "Built-in",
        "t2p_status_unavailable": "Unavailable",
        "t2p_reset_done": "↺ Reset",
        "t2p_file_required": (
            "✗ Provide the path to a .py file\n"
            "Or install the built-in one: pip install \"nl2prolog[ru]\""
        ),
        "t2p_file_missing": "✗ File not found: {path}",
        "t2p_not_py": "✗ Expected a .py file, got: {path}",
        "t2p_spec_failed": "✗ Could not create a loader for: {path}",
        "t2p_import_failed":
            "✗ Import error {path}:\n{e}\n\n{tb}",
        "t2p_no_class":
            "✗ Module has no TextToProlog class: {path}",
        "t2p_no_method":
            "✗ TextToProlog has neither parse() nor convert(): {path}",
        "t2p_no_init":
            "✗ TextToProlog cannot be constructed without args:\n{e}",
        "t2p_loaded":
            "✓ Loaded module: {path}\n"
            "  class: TextToProlog\n"
            "  as sys.modules['{name}']",

        # extractor banner
        "nl_banner_custom":
            "✅ <b>Custom extractor</b> connected.<br>"
            "NL import works through your .py module.",
        "nl_banner_pkg":
            "✅ <b>nl2prolog {v}</b> — default extractor.<br>"
            "NL import works out of the box.",
        "nl_banner_pkg_no_shim":
            "⚠️ <b>nl2prolog {v}</b> is installed, but the "
            "<code>text_to_prolog</code> shim is not loading.<br>"
            "Check the package installation, or load your own "
            ".py extractor in the “⚙️ Custom converter” section below.",
        "nl_banner_local":
            "✅ <b>Built-in text_to_prolog</b> loaded "
            "(the nl2prolog package was not found).<br>"
            "NL import works through the local module.",
        "nl_banner_none":
            "ℹ️ <b>NL extractor is not set.</b><br>"
            "The graph editor works fully — you can open/save "
            "<code>.pl</code>, edit nodes/edges/attributes, "
            "import Prolog code, and run queries.<br>"
            "NL import (📥 Extract facts / queries) is unavailable.<br>"
            "→ <b>Load your own <code>.py</code> extractor</b> in the "
            "“⚙️ Custom converter” section below.<br>"
            "→ <b>Or install:</b> <code>pip install \"nl2prolog[ru]\"</code>",

        # extractor hint in handlers
        "extractor_hint":
            "ℹ️ NL extractor is not set.\n\n"
            "The graph editor works fully — you can open/save .pl, "
            "edit nodes/edges/attributes, import Prolog code, "
            "run queries.\n\n"
            "For NL import you need to:\n"
            "  → Load your own .py module with a TextToProlog class\n"
            "    in the “⚙️ Custom converter” section\n"
            "    (parse() or convert() method)\n"
            "  → Or install the built-in one:\n"
            "    pip install \"nl2prolog[ru]\"\n",

        # import Prolog accordion
        "imp_prolog_title": "📥 Import from Prolog",
        "imp_prolog_placeholder": "% Paste Prolog code",
        "imp_prolog_btn": "📥 Parse",
        "imp_prolog_ready": "Ready.",

        # diagnostics
        "diag_title": "🔬 Diagnostics",
        "diag_show": "🔄 Show",

        # editor tabs
        "tab_nodes": "Nodes",
        "tab_edges": "Edges",
        "tab_attrs": "Attributes",
        "tab_filtered": "🛡️ Filtered",
        "tab_dialog": "💬 Dialog",
        "tab_source": "Prolog source",

        # nodes
        "nodes_headers": ["id", "type", "degree"],
        "nodes_id_placeholder": "id (apple)",
        "nodes_type_placeholder": "type (org, person...)",
        "nodes_edit_id_placeholder": "ID",
        "nodes_edit_type_placeholder": "Type",
        "nodes_add_btn": "➕",
        "nodes_edit_btn": "💾",
        "nodes_del_btn": "🗑️",
        "nodes_click_hint": "✗ Click a row in the table",
        "nodes_not_found": "✗ Node not found",
        "nodes_already_exists": "✗ Node '{id}' already exists",
        "nodes_rename_err": "✗ Rename error: {e}",
        "nodes_edit_err": "✗ Error: {e}",
        "nodes_updated": "✓ Node updated: {id}",
        "nodes_deleted": "✓ Node {id} deleted",

        # edges
        "edges_headers": ["idx", "source", "predicate", "target"],
        "edges_src_placeholder": "source",
        "edges_tgt_placeholder": "target",
        "edges_pred_placeholder": "predicate",
        "edges_edit_src_placeholder": "Source",
        "edges_edit_tgt_placeholder": "Target",
        "edges_edit_pred_placeholder": "Predicate",
        "edges_add_btn": "➕",
        "edges_edit_btn": "💾",
        "edges_del_btn": "🗑️",
        "edges_click_hint": "✗ Click a row in the table",
        "edges_not_found": "✗ Edge not found",
        "edges_node_err": "✗ Node add error: {e}",
        "edges_updated": "✓ Edge updated: {s} -> {t}",
        "edges_deleted": "✓ Edge deleted",

        # attributes
        "attrs_empty": "No attributes",
        "attrs_ent_placeholder": "entity",
        "attrs_name_placeholder": "name",
        "attrs_value_placeholder": "value",
        "attrs_add_btn": "➕",
        "attrs_del_placeholder": "Delete",
        "attrs_del_btn": "🗑️",

        # filtered
        "filtered_empty":
            "Nothing filtered (or logging is off).\n"
            "Enable “🛡️ Log filtered” in the NL import block.",
        "filtered_headers": ["term / atom", "filter reason"],

        # dialog
        "dialog_help":
            "Ask a question or make an assertion in natural language. "
            "Question → attempt to find an answer in the graph. "
            "Assertion → extracted facts are added to the graph. "
            "If no answer is found — clarify (✅/❌) or enter new text.",
        "dialog_not_started":
            "Dialog not started. Type a question and press “▶ Ask”.",
        "dialog_pending_none":
            "No pending question. Ask a new question or enter a statement.",
        "dialog_pending_label": "⏳ Pending question:",
        "dialog_pending_prolog": "Prolog:",
        "dialog_text_placeholder": "For example: Do I have a license?",
        "dialog_ask": "▶ Ask",
        "dialog_answer": "💬 Answer",
        "dialog_yes": "✅",
        "dialog_no": "❌",
        "dialog_reset": "🗑️",
        "dialog_status_ready": "Ready for dialog",
        "dialog_transcript_head": "📜 Transcript",
        "dialog_transcript_none": "(dialog not started)",
        "dialog_transcript_empty": "(empty)",
        "dialog_transcript_err": "(transcript read error)",
        "dialog_unavailable":
            "⚠️ <b>Dialog mode is unavailable.</b><br>"
            "The <code>dialog</code> module is not loading — the "
            "<code>nl2prolog</code> package is required.<br>"
            "→ Install: <code>pip install \"nl2prolog[ru]\"</code><br>"
            "→ A custom <code>.py</code> extractor is not enough "
            "for dialog mode (need <code>DialogTurn</code> from "
            "<code>nl2prolog</code>).<br>"
            "→ Check the console for <code>nl2prolog.dialog</code> "
            "import errors.",
        "dialog_empty_input": "✗ Empty input",
        "dialog_empty_answer": "✗ Empty answer",
        "dialog_unavailable_short":
            "✗ dialog.py is unavailable. "
            "Install: pip install \"nl2prolog[ru]\"",
        "dialog_init_failed":
            "✗ Could not initialize the dialog. "
            "Check that nl2prolog is installed and the extractor is set.",
        "dialog_not_initialized":
            "✗ Dialog not initialized. Press “▶ Ask” first.",
        "dialog_no_pending":
            "ℹ️ No pending question. Press “▶ Ask” first.",
        "dialog_reset_ok":
            "✓ Dialog reset (pending cleared, history kept)",
        "dialog_unrecognized":
            "\n⚠️ The question was not recognized by the parser "
            "(the NL extractor returned an empty query). "
            "Only facts from the text were extracted.\n"
            "💡 Try rephrasing the question.",
        "dialog_no_solution_hint":
            "\n💡 No solution found. Press ✅ Yes / ❌ No "
            "or enter a clarification.",
        "dialog_facts_added":
            "\n✓ Facts added: +{n} nodes, +{e} edges, +{a} attributes",
        "dialog_facts_err": "\n✗ Fact add error: {e}",

        # source tab
        "src_refresh_btn": "🔄 Refresh from graph",
        "src_apply_btn": "📥 Apply",
        "src_edit_accordion": "✏️ Edit",
        "src_code_placeholder": "% Press 🔄",
        "src_preview_empty":
            "Press 🔄 “Refresh from graph” to serialize",
        "src_ready": "Ready.",
        "src_parsed": "✓ Parsed",

        # queries
        "query_placeholder": "edge(X, Y, owns).",
        "query_run_btn": "▶ Query",
        "query_help_btn": "ℹ️ Help",
        "query_empty": "✗ Empty query",
        "query_engine_missing":
            "✗ Install prolog",
        "query_agent_err": "✗ Agent error: {e}",
        "query_no_solutions": "✗ No solutions",
        "query_true": "✓ true",
        "query_none": "No solutions",
        "query_found": "✓ {n} solution(s)",
        "query_help_text":
            "Available: edge/2,3 node/2,3 attribute/3 findall/3, etc.",
        "query_agent_not_loaded": "⚠️ PyAgentProlog not loaded",

        # status labels
        "file_not_selected": "File not selected",
        "cancelled": "Cancelled",
        "cleared": "Cleared",
        "ready": "Ready.",
        "paste_prolog": "% Paste Prolog code",

        # file loading
        "file_read_ok":
            "✅ File loaded ({n} chars). "
            "Press “📝 Open text” to view and edit.",
        "file_read_err": "❌ Could not read file: {path}",
        "file_apply_ok": "✅ Text updated.",
        "file_unsupported": "❌ Unsupported format: {ext}",
        "file_read_exception": "❌ File read error: {e}",
        "file_pdf_dep": "❌ To read PDF install: pip install PyPDF2",
        "file_docx_dep": "❌ To read DOCX install: pip install python-docx",

        # project handlers
        "proj_merged_ok":
            "✓ Merged: {path}\n"
            "  +{an} nodes, +{ae} edges, +{aa} attributes\n"
            "  skipped (already present or invalid): "
            "{sn} nodes, {se} edges, {sa} attributes",
        "proj_merged_nothing":
            "ℹ️ Nothing to add: {path}\n"
            "  Everything is already in the graph "
            "({sk} items skipped).",
        "proj_merged_empty": "ℹ️ File is empty: {path}",
        "proj_merge_err": "✗ Merge error: {e}",
        "proj_loaded": "✓ Loaded: {path}",
        "proj_saved": "✓ Saved: {path}",
        "proj_save_no_file": "✗ No file selected",
        "proj_new_ok": "✓ Project: {path}",
        "proj_example_ok": "✓ Demo graph",

        # dialog / chat
        "dlg_ready": "Ready for dialog",
        "dlg_no_dialog": "(dialog not started)",
    },
    "ru": {
        "title": "KnowledgeGraph Editor",
        "lang_override_hint":
            "переопределение: KG_EDITOR_LANG=en|ru",

        "col_project": "📁 Граф / Проект",
        "col_editor": "🧩 Редактор графа",
        "col_visual": "🖼️ Визуализация (PyVis)",
        "col_queries": "🔎 Запросы",

        "btn_open": "📂 Открыть",
        "btn_merge": "🔀 Объединить",
        "btn_new": "🆕 Создать",
        "btn_save": "💾 Сохранить",
        "btn_example": "📚",

        "stats_nodes": "Узлов:",
        "stats_edges": "Рёбер:",
        "stats_attrs": "Атрибутов:",

        "nl_import_title": "📝 Импорт из НЛ",
        "nl_file_label": "Файл (txt, pdf, docx, fb2)",
        "nl_open_text_btn": "📝 Открыть текст",
        "nl_short_text_label": "Краткий текст",
        "nl_btn_facts": "📊 Факты",
        "nl_btn_query": "❓ Запрос",
        "nl_btn_clear": "🗑️",
        "nl_log_filtered": "🛡️ Логировать отфильтрованное",
        "nl_status_ready": "Готов.",
        "custom_conv_title": "⚙️ Пользовательский конвертер",
        "t2p_path_placeholder": "Путь к .py-файлу",
        "t2p_pick": "📂 Выбрать",
        "t2p_load": "✅ Загрузить",
        "t2p_reset": "↺ Встроенный",
        "t2p_status_builtin": "Встроенный",
        "t2p_status_unavailable": "Недоступен",
        "t2p_reset_done": "↺ Сброшено",
        "t2p_file_required":
            "✗ Укажите путь к .py-файлу\n"
            "Или установите встроенный: pip install \"nl2prolog[ru]\"",
        "t2p_file_missing": "✗ Файл не найден: {path}",
        "t2p_not_py": "✗ Ожидался .py-файл, получено: {path}",
        "t2p_spec_failed":
            "✗ Не удалось создать загрузчик для: {path}",
        "t2p_import_failed":
            "✗ Ошибка импорта {path}:\n{e}\n\n{tb}",
        "t2p_no_class":
            "✗ В модуле нет класса TextToProlog: {path}",
        "t2p_no_method":
            "✗ Класс TextToProlog не имеет ни parse(), ни convert(): {path}",
        "t2p_no_init":
            "✗ Класс TextToProlog не инициализируется без аргументов:\n{e}",
        "t2p_loaded":
            "✓ Загружен модуль: {path}\n"
            "  класс: TextToProlog\n"
            "  as sys.modules['{name}']",

        "nl_banner_custom":
            "✅ <b>Пользовательский экстрактор</b> подключён.<br>"
            "NL-импорт работает через ваш .py-модуль.",
        "nl_banner_pkg":
            "✅ <b>nl2prolog {v}</b> — экстрактор по умолчанию.<br>"
            "NL-импорт работает из коробки.",
        "nl_banner_pkg_no_shim":
            "⚠️ <b>nl2prolog {v}</b> установлен, "
            "но shim <code>text_to_prolog</code> не загружается.<br>"
            "Проверьте установку пакета, либо загрузите свой "
            ".py-экстрактор в разделе «⚙️ Пользовательский конвертер» ниже.",
        "nl_banner_local":
            "✅ <b>Встроенный text_to_prolog</b> загружен "
            "(пакет nl2prolog не обнаружен).<br>"
            "NL-импорт работает через локальный модуль.",
        "nl_banner_none":
            "ℹ️ <b>Экстрактор NL не задан.</b><br>"
            "Редактор графа работает полностью — можно открывать/сохранять "
            "<code>.pl</code>, редактировать узлы/рёбра/атрибуты, "
            "импортировать Prolog-код, строить запросы.<br>"
            "NL-импорт (📥 Извлечь факты / запросы) недоступен.<br>"
            "→ <b>Загрузите свой <code>.py</code>-экстрактор</b> в разделе "
            "«⚙️ Пользовательский конвертер» ниже.<br>"
            "→ <b>Или установите:</b> <code>pip install \"nl2prolog[ru]\"</code>",

        "extractor_hint":
            "ℹ️ Экстрактор NL не задан.\n\n"
            "Редактор графа работает полностью — можно открывать/сохранять .pl, "
            "редактировать узлы/рёбра/атрибуты, импортировать Prolog-код, "
            "строить запросы.\n\n"
            "Для NL-импорта нужно:\n"
            "  → Загрузить свой .py-модуль с классом TextToProlog\n"
            "    в разделе «⚙️ Пользовательский конвертер»\n"
            "    (метод parse() или convert())\n"
            "  → Или установить встроенный:\n"
            "    pip install \"nl2prolog[ru]\"\n",

        "imp_prolog_title": "📥 Импорт из Prolog",
        "imp_prolog_placeholder": "% Вставьте Prolog-код",
        "imp_prolog_btn": "📥 Разобрать",
        "imp_prolog_ready": "Готов.",

        "diag_title": "🔬 Диагностика",
        "diag_show": "🔄 Показать",

        "tab_nodes": "Узлы",
        "tab_edges": "Рёбра",
        "tab_attrs": "Атрибуты",
        "tab_filtered": "🛡️ Отфильтровано",
        "tab_dialog": "💬 Диалог",
        "tab_source": "Prolog source",

        "nodes_headers": ["id", "type", "degree"],
        "nodes_id_placeholder": "id (apple)",
        "nodes_type_placeholder": "type (org, person...)",
        "nodes_edit_id_placeholder": "ID",
        "nodes_edit_type_placeholder": "Type",
        "nodes_add_btn": "➕",
        "nodes_edit_btn": "💾",
        "nodes_del_btn": "🗑️",
        "nodes_click_hint": "✗ Кликните по строке в таблице",
        "nodes_not_found": "✗ Узел не найден",
        "nodes_already_exists": "✗ Узел '{id}' уже существует",
        "nodes_rename_err": "✗ Ошибка переименования: {e}",
        "nodes_edit_err": "✗ Ошибка: {e}",
        "nodes_updated": "✓ Узел обновлён: {id}",
        "nodes_deleted": "✓ Узел {id} удалён",

        "edges_headers": ["idx", "source", "predicate", "target"],
        "edges_src_placeholder": "source",
        "edges_tgt_placeholder": "target",
        "edges_pred_placeholder": "predicate",
        "edges_edit_src_placeholder": "Source",
        "edges_edit_tgt_placeholder": "Target",
        "edges_edit_pred_placeholder": "Predicate",
        "edges_add_btn": "➕",
        "edges_edit_btn": "💾",
        "edges_del_btn": "🗑️",
        "edges_click_hint": "✗ Кликните по строке в таблице",
        "edges_not_found": "✗ Ребро не найдено",
        "edges_node_err": "✗ Ошибка добавления узла: {e}",
        "edges_updated": "✓ Ребро обновлено: {s} -> {t}",
        "edges_deleted": "✓ Ребро удалено",

        "attrs_empty": "Нет атрибутов",
        "attrs_ent_placeholder": "entity",
        "attrs_name_placeholder": "name",
        "attrs_value_placeholder": "value",
        "attrs_add_btn": "➕",
        "attrs_del_placeholder": "Удалить",
        "attrs_del_btn": "🗑️",

        "filtered_empty":
            "Ничего не отфильтровано (или логирование выключено).\n"
            "Включите «🛡️ Логировать отфильтрованное» в блоке импорта НЛ.",
        "filtered_headers": ["терм / атом", "причина фильтрации"],

        "dialog_help":
            "Задайте вопрос или утверждение на естественном языке. "
            "Вопрос → попытка найти ответ в графе. "
            "Утверждение → извлечённые факты добавятся в граф. "
            "Если ответ не найден — уточните (✅/❌) или введите новый текст.",
        "dialog_not_started":
            "Диалог не начат. Введите вопрос и нажмите «▶ Спросить».",
        "dialog_pending_none":
            "Нет ожидающего вопроса. Задайте новый вопрос или введите утверждение.",
        "dialog_pending_label": "⏳ Ожидающий вопрос:",
        "dialog_pending_prolog": "Prolog:",
        "dialog_text_placeholder": "Например: У меня есть лицензия?",
        "dialog_ask": "▶ Спросить",
        "dialog_answer": "💬 Ответить",
        "dialog_yes": "✅",
        "dialog_no": "❌",
        "dialog_reset": "🗑️",
        "dialog_status_ready": "Готов к диалогу",
        "dialog_transcript_head": "📜 Транскрипт",
        "dialog_transcript_none": "(диалог не начат)",
        "dialog_transcript_empty": "(пусто)",
        "dialog_transcript_err": "(ошибка чтения транскрипта)",
        "dialog_unavailable":
            "⚠️ <b>Диалоговый режим недоступен.</b><br>"
            "Модуль <code>dialog</code> не загружается — "
            "нужен пакет <code>nl2prolog</code>.<br>"
            "→ Установите: <code>pip install \"nl2prolog[ru]\"</code><br>"
            "→ Пользовательский <code>.py</code>-экстрактор "
            "для диалога недостаточен (нужен <code>DialogTurn</code> "
            "из <code>nl2prolog</code>).<br>"
            "→ Проверьте консоль на ошибки импорта <code>nl2prolog.dialog</code>.",
        "dialog_empty_input": "✗ Пустой ввод",
        "dialog_empty_answer": "✗ Пустой ответ",
        "dialog_unavailable_short":
            "✗ dialog.py недоступен. "
            "Установите: pip install \"nl2prolog[ru]\"",
        "dialog_init_failed":
            "✗ Не удалось инициализировать диалог. "
            "Проверьте, что установлен nl2prolog и задан экстрактор.",
        "dialog_not_initialized":
            "✗ Диалог не инициализирован. Сначала нажмите «▶ Спросить».",
        "dialog_no_pending":
            "ℹ️ Нет ожидающего вопроса. Сначала нажмите «▶ Спросить».",
        "dialog_reset_ok":
            "✓ Диалог сброшен (pending очищен, история сохранена)",
        "dialog_unrecognized":
            "\n⚠️ Вопрос не распознан парсером "
            "(NL-экстрактор вернул пустой запрос). "
            "Извлечены только факты из текста.\n"
            "💡 Попробуйте переформулировать вопрос.",
        "dialog_no_solution_hint":
            "\n💡 Решение не найдено. Нажмите ✅ Да / ❌ Нет "
            "или введите уточнение.",
        "dialog_facts_added":
            "\n✓ Факты добавлены: +{n} узлов, +{e} рёбер, +{a} атрибутов",
        "dialog_facts_err": "\n✗ Ошибка добавления фактов: {e}",

        "src_refresh_btn": "🔄 Обновить из графа",
        "src_apply_btn": "📥 Применить",
        "src_edit_accordion": "✏️ Редактировать",
        "src_code_placeholder": "% Нажмите 🔄",
        "src_preview_empty":
            "Нажмите 🔄 «Обновить из графа» для сериализации",
        "src_ready": "Готов.",
        "src_parsed": "✓ Разобрано",

        "query_placeholder": "edge(X, Y, owns).",
        "query_run_btn": "▶ Запрос",
        "query_help_btn": "ℹ️ Помощь",
        "query_empty": "✗ Пустой запрос",
        "query_engine_missing": "✗ Установите prolog",
        "query_agent_err": "✗ Ошибка агента: {e}",
        "query_no_solutions": "✗ Нет решений",
        "query_true": "✓ true",
        "query_none": "Нет решений",
        "query_found": "✓ {n} решение(й)",
        "query_help_text":
            "Доступно: edge/2,3 node/2,3 attribute/3 findall/3 и т.д.",
        "query_agent_not_loaded": "⚠️ PyAgentProlog не загружен",

        "file_not_selected": "Файл не выбран",
        "cancelled": "Отменено",
        "cleared": "Очищено.",
        "ready": "Готов.",
        "paste_prolog": "% Вставьте Prolog-код",

        "file_read_ok":
            "✅ Файл загружен ({n} символов). "
            "Нажмите «📝 Открыть текст», чтобы просмотреть и отредактировать.",
        "file_read_err": "❌ Не удалось прочитать файл: {path}",
        "file_apply_ok": "✅ Текст обновлён.",
        "file_unsupported": "❌ Неподдерживаемый формат: {ext}",
        "file_read_exception": "❌ Ошибка чтения файла: {e}",
        "file_pdf_dep": "❌ Для чтения PDF установите: pip install PyPDF2",
        "file_docx_dep":
            "❌ Для чтения DOCX установите: pip install python-docx",

        "proj_merged_ok":
            "✓ Объединено: {path}\n"
            "  +{an} узлов, +{ae} рёбер, +{aa} атрибутов\n"
            "  пропущено (уже есть или невалидно): "
            "{sn} узлов, {se} рёбер, {sa} атрибутов",
        "proj_merged_nothing":
            "ℹ️ Нечего добавлять: {path}\n"
            "  Всё уже есть в графе ({sk} элементов пропущено).",
        "proj_merged_empty": "ℹ️ Файл пуст: {path}",
        "proj_merge_err": "✗ Ошибка объединения: {e}",
        "proj_loaded": "✓ Загружено: {path}",
        "proj_saved": "✓ Сохранено: {path}",
        "proj_save_no_file": "✗ Не выбран файл",
        "proj_new_ok": "✓ Проект: {path}",
        "proj_example_ok": "✓ Демо-граф",

        "dlg_ready": "Готов к диалогу",
        "dlg_no_dialog": "(диалог не начат)",
    },
}


def t(lang: str, key: str, **kwargs) -> str:
    """Look up a translated string for the given language."""
    table = TRANSLATIONS.get(lang) or TRANSLATIONS["en"]
    value = table.get(key)
    if value is None:
        value = TRANSLATIONS["en"].get(key, key)
    return value.format(**kwargs) if kwargs and isinstance(value, str) else value


def _detect_system_lang() -> str:
    """Detect system language (en/ru); overridable via env var."""
    override = os.environ.get("KG_EDITOR_LANG", "").strip().lower()
    if override in ("en", "ru"):
        return override
    try:
        import locale
        loc = (locale.getlocale()[0] or "").lower()
        if loc.startswith("ru"):
            return "ru"
    except (ValueError, TypeError, AttributeError):
        pass
    for var in ("LANG", "LC_ALL", "LANGUAGE", "LC_MESSAGES"):
        if os.environ.get(var, "").lower().startswith("ru"):
            return "ru"
    if _sys.platform == "win32":
        try:
            import ctypes
            if (ctypes.windll.kernel32.GetUserDefaultUILanguage()
                    & 0x3FF) == 0x19:
                return "ru"
        except Exception:
            pass
    return "en"


# =====================================================================
# Constants
# =====================================================================
_CONVENIENCE_RULES = """
% --- convenience rules (added by the editor) ---
node(Id, Type) :- node(Id, _, Type).
edge(S, T) :- edge(S, T, _).
"""

_SOLUTION_LIMIT = 1000


# =====================================================================
# Theme (GitHub-dark) + forced dark
# =====================================================================
def _make_theme() -> gr.themes.Base:
    t_ = gr.themes.Base(
        primary_hue=gr.themes.colors.blue,
        neutral_hue=gr.themes.colors.slate,
    )
    return t_.set(
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
        btn.title = isFs ? 'Collapse' : 'Expand to full screen';
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
# CSS (unchanged)
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

/* =====================================================================
   v5.12.1 — single border for text inputs (.compact-tb)

   Gradio wraps <input>/<textarea> in .block/.form that also gets a
   border from the theme (block_border_color). Inside, the input itself
   has a border → visually two outlines. We strip border/background/
   shadow from the wrapper and keep only the input field visible.
   ===================================================================== */
.gradio-container .compact-tb,
.gradio-container .compact-tb.block,
.gradio-container .compact-tb .form,
.gradio-container .compact-tb .wrap {
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
    padding: 0 !important;
}
.gradio-container .compact-tb input,
.gradio-container .compact-tb textarea {
    padding: 4px 8px !important;
    font-size: 12px !important;
    min-height: 28px !important;
    background: #0b0d11 !important;
    color: #c7cbd1 !important;
    border: 1px solid #2a313d !important;
    border-radius: 4px !important;
    outline: none !important;
    box-sizing: border-box !important;
    width: 100% !important;
}
.gradio-container .compact-tb input:focus,
.gradio-container .compact-tb textarea:focus {
    border-color: #58a6ff !important;
    box-shadow: 0 0 0 2px rgba(88,166,255,.2) !important;
    outline: none !important;
}

.gradio-container .modal-textarea,
.gradio-container .modal-textarea.block,
.gradio-container .modal-textarea .form {
    border: none !important;
    background: transparent !important;
    padding: 0 !important;
}
.gradio-container .modal-textarea textarea {
    border: 1px solid #2a313d !important;
    border-radius: 4px !important;
    background: #0b0d11 !important;
    color: #c7cbd1 !important;
}
.gradio-container .modal-textarea textarea:focus {
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

.gradio-container .block:has(.cm-editor) {
    border: none !important;
    background: transparent !important;
    padding: 0 !important;
}
.gradio-container .cm-editor {
    border: 1px solid #2a313d !important;
    border-radius: 4px !important;
}
.gradio-container .cm-editor.cm-focused {
    border-color: #58a6ff !important;
    box-shadow: 0 0 0 2px rgba(88,166,255,.2) !important;
}

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
# Basic utilities
# =====================================================================
def _status_html(s: str) -> str:
    return f'<pre class="status-box">{_esc(str(s))}</pre>'


def _nl_package_status_html(lang: str = "en",
                            t2p_custom: bool = False) -> str:
    """Banner describing the default extractor state.

    t2p_custom=True — the user loaded their own .py via the UI.
    Otherwise determined automatically from _T2P_OK / _NL2PROLOG_OK.
    """
    base = (
        "padding:8px 10px;border-radius:4px;font-size:11px;"
        "font-family:ui-sans-serif,system-ui,sans-serif;"
        "line-height:1.55;"
    )
    if t2p_custom:
        return (
            f'<div style="{base}background:#0d1117;'
            f'border:1px solid #238636;color:#7ee787;">'
            f'{t(lang, "nl_banner_custom")}</div>'
        )
    if _T2P_OK and _NL2PROLOG_OK:
        return (
            f'<div style="{base}background:#0d1117;'
            f'border:1px solid #238636;color:#7ee787;">'
            f'{t(lang, "nl_banner_pkg", v=_esc(_NL2PROLOG_VERSION))}</div>'
        )
    if _NL2PROLOG_OK and not _T2P_OK:
        return (
            f'<div style="{base}background:#161a20;'
            f'border:1px solid #f0883e;color:#f0883e;">'
            f'{t(lang, "nl_banner_pkg_no_shim", v=_esc(_NL2PROLOG_VERSION))}'
            f'</div>'
        )
    if _T2P_OK and not _NL2PROLOG_OK:
        return (
            f'<div style="{base}background:#0d1117;'
            f'border:1px solid #238636;color:#7ee787;">'
            f'{t(lang, "nl_banner_local")}</div>'
        )
    return (
        f'<div style="{base}background:#161a20;'
        f'border:1px solid #f0883e;color:#f0883e;">'
        f'{t(lang, "nl_banner_none")}</div>'
    )


def _safe(g) -> KnowledgeGraph:
    return g if isinstance(g, KnowledgeGraph) else KnowledgeGraph()


def _stats_html(g: KnowledgeGraph, lang: str = "en") -> str:
    s = g.summary()
    return (
        '<div class="proj-info">'
        f'<b>{t(lang, "stats_nodes")}</b> {s["nodes"]} &nbsp; '
        f'<b>{t(lang, "stats_edges")}</b> {s["edges"]} &nbsp; '
        f'<b>{t(lang, "stats_attrs")}</b> {s["attributes"]}'
        '</div>'
    )


def _graph_to_program(g: KnowledgeGraph) -> str:
    return g.to_prolog() + _CONVENIENCE_RULES


# =====================================================================
# Table data (lists of lists with HTML)
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

def _node_type_color(t_: str) -> str:
    return _NODE_TYPE_COLORS.get((t_ or "").lower(),
                                 _NODE_TYPE_COLORS["default"])


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
        type_html = (
            f'<span style="background-color:{color}22; color:{color}; '
            f'padding:2px 6px; border-radius:4px; '
            f'border:1px solid {color}66;">{n.type}</span>'
        )
        rows.append([n.id, type_html, str(deg[n.id])])
    return rows


def _edges_data(g: KnowledgeGraph) -> List[List[str]]:
    rows = []
    for i, e in enumerate(g.edges):
        src_color = (_node_type_color(g.nodes[e.source].type)
                     if e.source in g.nodes else "#8b949e")
        tgt_color = (_node_type_color(g.nodes[e.target].type)
                     if e.target in g.nodes else "#8b949e")

        src_html = (
            f'<span style="background-color:{src_color}22; '
            f'color:{src_color}; padding:2px 6px; border-radius:4px; '
            f'border:1px solid {src_color}66;">{e.source}</span>'
        )
        tgt_html = (
            f'<span style="background-color:{tgt_color}22; '
            f'color:{tgt_color}; padding:2px 6px; border-radius:4px; '
            f'border:1px solid {tgt_color}66;">{e.target}</span>'
        )
        pred_html = (
            f'<span style="color:#ff7b72; font-family:monospace;">'
            f'─[{e.predicate}]→</span>'
        )

        rows.append([str(i), src_html, pred_html, tgt_html])
    return rows


# =====================================================================
# Colored chips (for HTML tables of attributes and filters)
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
        'font-family:ui-sans-serif,system-ui,sans-serif;'
        'white-space:pre-wrap;">'
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


def _attrs_html(g: KnowledgeGraph, lang: str = "en") -> str:
    if not g.attributes:
        return _empty_table_html(t(lang, "attrs_empty"))
    rows: List[str] = []
    for i, a in enumerate(g.attributes):
        color = (_node_type_color(g.nodes[a.entity].type)
                 if a.entity in g.nodes else "#8b949e")
        rows.append(
            "<tr>"
            f'<td style="padding:4px 10px;border-bottom:1px solid #161a20;'
            f'color:#6e7681;text-align:right;'
            f'font-family:ui-monospace,monospace;width:32px;">{i}</td>'
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
    headers = ["idx", "entity", "name", "value"]
    return _table_wrap(headers, rows,
                       align=["right", "left", "left", "left"])


def _filtered_html(items: List[Tuple[str, str]], lang: str = "en") -> str:
    if not items:
        return _empty_table_html(t(lang, "filtered_empty"))
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
    return _table_wrap(t(lang, "filtered_headers"), rows,
                       align=["left", "left"])


# =====================================================================
# Prolog syntax highlighting
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


def _prolog_code_html(src: str, lang: str = "en") -> str:
    if not src or not src.strip():
        return _empty_table_html(t(lang, "src_preview_empty"))
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
# Refresh — uniform tuple for all tables
# =====================================================================
def _refresh(g: KnowledgeGraph, lang: str = "en"):
    return (
        g,
        _nodes_data(g),
        _edges_data(g),
        _attrs_html(g, lang),
        _stats_html(g, lang),
        render_pyvis(g),
    )


def _serialize_and_preview(g, lang: str = "en"):
    src = g.to_prolog() if isinstance(g, KnowledgeGraph) else ""
    return src, _prolog_code_html(src, lang)


# ---- File pickers ----------------------------------------------------
def _pick_file(initial: str = "", title: str = "Select file",
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


def _pick_folder(initial: str = "", title: str = "Project folder"
                 ) -> Optional[str]:
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
# Text extraction from files
# =====================================================================
def extract_text_from_file(file_path: str, lang: str = "en"
                           ) -> Optional[str]:
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
                    return '\n'.join([
                        page.extract_text() for page in reader.pages
                        if page.extract_text()
                    ])
            except ImportError:
                return t(lang, "file_pdf_dep")
        elif ext == '.docx':
            try:
                import docx
                doc = docx.Document(file_path)
                return '\n'.join([p.text for p in doc.paragraphs])
            except ImportError:
                return t(lang, "file_docx_dep")
        else:
            return t(lang, "file_unsupported", ext=ext)
    except Exception as e:
        return t(lang, "file_read_exception", e=e)


def h_load_text_file(file, lang: str = "en"):
    if file is None:
        return ("", _status_html(t(lang, "file_not_selected")),
                gr.update(visible=False), gr.update(visible=False))
    path = file.name if hasattr(file, "name") else str(file)
    text = extract_text_from_file(path, lang)
    if not text:
        return ("", _status_html(t(lang, "file_read_err", path=path)),
                gr.update(visible=False), gr.update(visible=False))
    if text.startswith("❌"):
        return ("", _status_html(text),
                gr.update(visible=False), gr.update(visible=False))
    return (
        text,
        _status_html(t(lang, "file_read_ok", n=len(text))),
        gr.update(visible=True),
        gr.update(visible=False),
    )


def h_open_modal(state_text):
    if not state_text:
        return gr.update(visible=False), ""
    return gr.update(visible=True), state_text


def h_apply_modal(modal_text_val, lang: str = "en"):
    return (gr.update(visible=False), modal_text_val,
            _status_html(t(lang, "file_apply_ok")))


def h_clear_nl(lang: str = "en"):
    return ("", "", _status_html(t(lang, "cleared")),
            gr.update(visible=False), gr.update(visible=False))


# =====================================================================
# Loading a custom TextToProlog
# =====================================================================
def _h_pick_t2p() -> str:
    p = _pick_file(
        title="Select text-to-prolog module (.py)",
        filetypes=[("Python (*.py)", "*.py"), ("All files", "*.*")],
    )
    return p or ""


def h_load_t2p_module(path: str, lang: str = "en"):
    path = (path or "").strip()
    if not path:
        return None, _status_html(t(lang, "t2p_file_required"))
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return None, _status_html(t(lang, "t2p_file_missing", path=path))
    if not path.endswith(".py"):
        return None, _status_html(t(lang, "t2p_not_py", path=path))

    mod_dir = os.path.dirname(path)
    if mod_dir and mod_dir not in _sys.path:
        _sys.path.insert(0, mod_dir)

    unique_name = f"_kg_editor_custom_t2p_{_uuid.uuid4().hex[:8]}"
    try:
        spec = importlib.util.spec_from_file_location(unique_name, path)
        if spec is None or spec.loader is None:
            return None, _status_html(
                t(lang, "t2p_spec_failed", path=path))
        module = importlib.util.module_from_spec(spec)
        _sys.modules[unique_name] = module
        spec.loader.exec_module(module)
    except Exception as e:
        _sys.modules.pop(unique_name, None)
        return None, _status_html(
            t(lang, "t2p_import_failed", path=path, e=e,
              tb=traceback.format_exc()))

    if not hasattr(module, "TextToProlog"):
        _sys.modules.pop(unique_name, None)
        return None, _status_html(
            t(lang, "t2p_no_class", path=path))

    cls = module.TextToProlog
    if not hasattr(cls, 'parse') and not hasattr(cls, 'convert'):
        _sys.modules.pop(unique_name, None)
        return None, _status_html(
            t(lang, "t2p_no_method", path=path))

    try:
        cls()
    except Exception as e:
        _sys.modules.pop(unique_name, None)
        return None, _status_html(t(lang, "t2p_no_init", e=e))

    return cls, _status_html(
        t(lang, "t2p_loaded", path=path, name=unique_name))


# =====================================================================
# Handlers — CRUD and selection
# =====================================================================
def h_add_node(g, nid, ntype, lang: str = "en"):
    g = _safe(g)
    try:
        g.add_node(nid, ntype or "concept")
        return (*_refresh(g, lang), "", "")
    except Exception as e:
        return (*_refresh(g, lang), "", f"✗ {e}")


def h_select_node(evt: gr.SelectData, g):
    g = _safe(g)
    row = evt.index[0]
    if 0 <= row < len(g.nodes):
        node_id = list(g.nodes.keys())[row]
        n = g.nodes[node_id]
        return n.id, n.type, node_id
    return "", "", ""


def h_edit_node(g, old_id, new_id, new_type, lang: str = "en"):
    g = _safe(g)
    if not old_id:
        return (*_refresh(g, lang), t(lang, "nodes_click_hint"))
    if old_id not in g.nodes:
        return (*_refresh(g, lang), t(lang, "nodes_not_found"))

    old_node = g.nodes[old_id]
    final_id = new_id.strip() if new_id and new_id.strip() else old_id
    final_type = (new_type.strip()
                  if new_type and new_type.strip() else old_node.type)

    if final_id != old_id:
        if final_id in g.nodes:
            return (*_refresh(g, lang),
                    t(lang, "nodes_already_exists", id=final_id))

        props = old_node.props
        try:
            g.add_node(final_id, final_type, props)
        except Exception as e:
            return (*_refresh(g, lang),
                    t(lang, "nodes_rename_err", e=e))

        for e in g.edges:
            if e.source == old_id:
                e.source = final_id
            if e.target == old_id:
                e.target = final_id

        for a in g.attributes:
            if a.entity == old_id:
                a.entity = final_id

        g.remove_node(old_id)
    else:
        try:
            g.add_node(old_id, final_type)
        except Exception as e:
            return (*_refresh(g, lang), t(lang, "nodes_edit_err", e=e))

    return (*_refresh(g, lang), t(lang, "nodes_updated", id=final_id))


def h_del_node_selected(g, selected_id, lang: str = "en"):
    g = _safe(g)
    if not selected_id:
        return (*_refresh(g, lang), t(lang, "nodes_click_hint"))
    if g.remove_node(selected_id):
        return (*_refresh(g, lang),
                t(lang, "nodes_deleted", id=selected_id))
    return (*_refresh(g, lang), t(lang, "nodes_not_found"))


def h_add_edge(g, src, tgt, pred, lang: str = "en"):
    g = _safe(g)
    try:
        g.add_edge(src, tgt, pred)
        return (*_refresh(g, lang), "", "", "")
    except Exception as e:
        return (*_refresh(g, lang), "", "", f"✗ {e}")


def h_select_edge(evt: gr.SelectData, g):
    g = _safe(g)
    row = evt.index[0]
    if 0 <= row < len(g.edges):
        e = g.edges[row]
        return e.source, e.target, e.predicate, str(row)
    return "", "", "", ""


def h_edit_edge(g, idx_str, new_src, new_tgt, new_pred, lang: str = "en"):
    g = _safe(g)
    if not idx_str:
        return (*_refresh(g, lang), t(lang, "edges_click_hint"))
    try:
        idx = int(idx_str)
        if not (0 <= idx < len(g.edges)):
            return (*_refresh(g, lang), t(lang, "edges_not_found"))

        old_edge = g.edges[idx]
        final_src = (new_src.strip()
                     if new_src and new_src.strip() else old_edge.source)
        final_tgt = (new_tgt.strip()
                     if new_tgt and new_tgt.strip() else old_edge.target)
        final_pred = (new_pred.strip()
                      if new_pred and new_pred.strip()
                      else old_edge.predicate)

        try:
            if final_src not in g.nodes:
                g.add_node(final_src)
            if final_tgt not in g.nodes:
                g.add_node(final_tgt)
        except Exception as e:
            return (*_refresh(g, lang),
                    t(lang, "edges_node_err", e=e))

        old_edge.source = final_src
        old_edge.target = final_tgt
        old_edge.predicate = final_pred

        return (*_refresh(g, lang),
                t(lang, "edges_updated", s=final_src, t_=final_tgt)
                if False else
                t(lang, "edges_updated", s=final_src, t=final_tgt))
    except Exception as e:
        return (*_refresh(g, lang), f"✗ {e}")


def h_del_edge_selected(g, idx_str, lang: str = "en"):
    g = _safe(g)
    if not idx_str:
        return (*_refresh(g, lang), t(lang, "edges_click_hint"))
    try:
        idx = int(idx_str)
        if g.remove_edge(idx):
            return (*_refresh(g, lang), t(lang, "edges_deleted"))
    except Exception:
        pass
    return (*_refresh(g, lang), t(lang, "edges_not_found"))


def h_add_attr(g, ent, name, value, lang: str = "en"):
    g = _safe(g)
    try:
        g.add_attribute(ent, name, value)
        return (*_refresh(g, lang), "", "", "")
    except Exception as e:
        return (*_refresh(g, lang), "", "", f"✗ {e}")


def h_del_attr(g, idx_str, lang: str = "en"):
    g = _safe(g)
    if idx_str is None:
        return _refresh(g, lang)
    try:
        g.remove_attribute(int(idx_str))
    except Exception:
        pass
    return _refresh(g, lang)


# =====================================================================
# Handlers — import
# =====================================================================
def _extractor_hint_html(lang: str = "en") -> str:
    """Hint for import handlers when the extractor is not set."""
    return t(lang, "extractor_hint")


def h_import_full_graph(g, short_text, full_text, t2p_cls=None,
                        log_filtered=False, lang: str = "en"):
    g = _safe(g)
    cls = t2p_cls if t2p_cls is not None \
        else (TextToProlog if _T2P_OK else None)
    if cls is None:
        return (_status_html(_extractor_hint_html(lang)), g,
                _filtered_html([], lang))
    text = (full_text or "").strip() or (short_text or "").strip()
    if not text:
        return _status_html("✗ " + t(lang, "empty_query")), g, \
               _filtered_html([], lang)

    try:
        t2p = cls()
        kwargs = {'strict': True, 'facts_from_questions': True}
        if log_filtered:
            kwargs['log_filtered'] = True

        try:
            facts_src, _ = t2p.parse(text, **kwargs)
        except TypeError:
            kwargs.pop('facts_from_questions', None)
            kwargs.pop('log_filtered', None)
            facts_src, _ = t2p.parse(text, **kwargs)

        filtered_items = (
            list(getattr(t2p, 'filtered_atoms', []) or [])
            if log_filtered else []
        )

        new_g = KnowledgeGraph.from_prolog(facts_src or "")
        for n in new_g.nodes.values():
            g.add_node(n.id, n.type, n.props)
        for e in new_g.edges:
            g.add_edge(e.source, e.target, e.predicate)
        for a in new_g.attributes:
            g.add_attribute(a.entity, a.name, a.value)

        msg = (f"✓ Facts: +{len(new_g.nodes)} nodes, "
               f"+{len(new_g.edges)} edges, "
               f"+{len(new_g.attributes)} attributes")
        return (_status_html(msg), g, _filtered_html(filtered_items, lang))
    except Exception as e:
        return _status_html(f"✗ {e}"), g, _filtered_html([], lang)


def h_extract_query(short_text, full_text, t2p_cls=None, lang: str = "en"):
    cls = t2p_cls if t2p_cls is not None \
        else (TextToProlog if _T2P_OK else None)
    if cls is None:
        return "", _status_html(_extractor_hint_html(lang))
    text = (full_text or "").strip() or (short_text or "").strip()
    if not text:
        return "", _status_html("✗ " + t(lang, "empty_query"))

    try:
        t2p = cls()
        try:
            _, query_src = t2p.parse(
                text, strict=True, facts_from_questions=False)
        except TypeError:
            _, query_src = t2p.parse(text, strict=True)

        if not query_src:
            return "", _status_html("ℹ️ No questions found.")
        return (query_src,
                _status_html(f"✓ Query extracted:\n{query_src[:100]}..."))
    except Exception as e:
        return "", _status_html(f"✗ {e}")


def h_parse_source(g, code, lang: str = "en"):
    try:
        new_g = KnowledgeGraph.from_prolog(code or "")
        return _refresh(new_g, lang)[0], _status_html(t(lang, "src_parsed"))
    except Exception as e:
        return g, _status_html(f"✗ {e}")


def h_merge_file(g, lang: str = "en"):
    """Merge the current graph with the graph from a file (additive)."""
    g = _safe(g)
    p = _pick_file(
        title="Merge with graph (.pl)",
        filetypes=[("Prolog (*.pl)", "*.pl"), ("All files", "*.*")],
    )
    if not p:
        return _refresh(g, lang) + (
            _status_html(t(lang, "file_not_selected")),)
    try:
        with open(p, encoding="utf-8") as f:
            content = f.read()
        stats = g.merge_from_prolog(content)

        added = (stats["added_nodes"]
                 + stats["added_edges"]
                 + stats["added_attributes"])
        skipped = (stats["skipped_nodes"]
                   + stats["skipped_edges"]
                   + stats["skipped_attributes"])

        if added == 0 and skipped == 0:
            msg = t(lang, "proj_merged_empty", path=p)
        elif added == 0:
            msg = t(lang, "proj_merged_nothing", path=p, sk=skipped)
        else:
            msg = t(lang, "proj_merged_ok",
                    path=p,
                    an=stats['added_nodes'],
                    ae=stats['added_edges'],
                    aa=stats['added_attributes'],
                    sn=stats['skipped_nodes'],
                    se=stats['skipped_edges'],
                    sa=stats['skipped_attributes'])
        return _refresh(g, lang) + (_status_html(msg),)
    except Exception as e:
        return _refresh(g, lang) + (
            _status_html(t(lang, "proj_merge_err", e=e)),)


def h_open_file(g, lang: str = "en"):
    p = _pick_file(title="Open graph .pl")
    if not p:
        return _refresh(_safe(g), lang) + (
            _status_html(t(lang, "file_not_selected")),)
    try:
        with open(p, encoding="utf-8") as f:
            new_g = KnowledgeGraph.from_prolog(f.read())
        return _refresh(new_g, lang) + (
            _status_html(t(lang, "proj_loaded", path=p)),)
    except Exception as e:
        return _refresh(_safe(g), lang) + (_status_html(f"✗ {e}"),)


def h_save_file(g, current_path, lang: str = "en"):
    g = _safe(g)
    p = current_path or _pick_file(title="Save as...", save=True)
    if not p:
        return _status_html(t(lang, "proj_save_no_file")), current_path
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write(g.to_prolog())
        return _status_html(t(lang, "proj_saved", path=p)), p
    except Exception as e:
        return _status_html(f"✗ {e}"), current_path


def h_new_project(g, lang: str = "en"):
    p = _pick_folder(title="New project folder")
    if not p:
        return _refresh(_safe(g), lang) + (
            _status_html(t(lang, "cancelled")),)
    try:
        os.makedirs(p, exist_ok=True)
        kb = os.path.join(p, "graph.pl")
        if not os.path.isfile(kb):
            with open(kb, "w", encoding="utf-8") as f:
                f.write("% Graph\n")
        new_g = KnowledgeGraph.from_prolog(
            open(kb, encoding="utf-8").read())
        return _refresh(new_g, lang) + (
            _status_html(t(lang, "proj_new_ok", path=p)),)
    except Exception as e:
        return _refresh(_safe(g), lang) + (_status_html(f"✗ {e}"),)


def h_load_example(g, lang: str = "en"):
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
    return _refresh(demo, lang) + (
        _status_html(t(lang, "proj_example_ok")),)


# =====================================================================
# Queries
# =====================================================================
def h_query(g, text, lang: str = "en"):
    g = _safe(g)
    text = (text or "").strip()
    if not text:
        return {"result": None}, t(lang, "query_empty")
    if not _AGENT_OK:
        return ({"error": "PyAgentProlog unavailable"},
                t(lang, "query_engine_missing"))

    q = text if text.endswith(".") else text + "."
    try:
        src = _graph_to_program(g)
        agent = Agent(src, context={})
    except Exception as e:
        return {"error": str(e)}, t(lang, "query_agent_err", e=e)

    sols, truncated = [], False
    try:
        for item in agent.stream(q):
            if isinstance(item, dict) and 'error' in item:
                return {"error": item['error']}, f"✗ {item['error']}"
            if item is False:
                return {"result": False}, t(lang, "query_no_solutions")
            if item is True:
                return {"result": True}, t(lang, "query_true")
            if isinstance(item, dict):
                sols.append(item)
            if len(sols) >= _SOLUTION_LIMIT:
                truncated = True
                break
    except Exception as e:
        return {"error": str(e)}, f"✗ {e}"

    if not sols:
        return {"result": None}, t(lang, "query_none")
    return sols, t(lang, "query_found", n=len(sols))


# =====================================================================
# Dialog helpers
# =====================================================================
def _dialog_unavailable_banner(lang: str = "en") -> str:
    return (
        '<div style="padding:8px 10px;background:#161a20;'
        'border:1px solid #f0883e;color:#f0883e;border-radius:4px;'
        'font-size:11px;line-height:1.55;'
        'font-family:ui-sans-serif,system-ui,sans-serif;">'
        f'{t(lang, "dialog_unavailable")}</div>'
    )


def _dialog_init(t2p_cls):
    """Create DialogTurn or None. Requires _DIALOG_OK and an extractor."""
    if not _DIALOG_OK or DialogTurn is None:
        return None
    cls = t2p_cls if t2p_cls is not None \
        else (TextToProlog if _T2P_OK else None)
    if cls is None:
        return None
    try:
        t2p = cls()
        agent = Agent if _AGENT_OK else None
        return DialogTurn(t2p=t2p, agent_factory=agent)
    except Exception:
        return None


def _dialog_transcript_str(dlg_state, lang: str = "en") -> str:
    if dlg_state is None:
        return t(lang, "dialog_transcript_none")
    try:
        txt = dlg_state.transcript(n=20)
        return txt if txt else t(lang, "dialog_transcript_empty")
    except Exception:
        return t(lang, "dialog_transcript_err")


def _dialog_pending_html(dlg_state, lang: str = "en") -> str:
    if dlg_state is None:
        return _empty_table_html(t(lang, "dialog_not_started"))
    pq = getattr(dlg_state, 'pending_query', '')
    pt = getattr(dlg_state, 'pending_question_text', '')
    if not pq:
        return _empty_table_html(t(lang, "dialog_pending_none"))
    return (
        '<div style="padding:8px 10px;background:#161a20;'
        'border:1px solid #58a6ff;border-radius:4px;'
        'font-size:12px;font-family:ui-monospace,monospace;'
        'line-height:1.55;">'
        f'<b style="color:#79c0ff;">{t(lang, "dialog_pending_label")}</b> '
        f'<span style="color:#c7cbd1;">{_esc(pt)}</span><br>'
        f'<b style="color:#8b949e;">{t(lang, "dialog_pending_prolog")}</b> '
        f'<code style="color:#ffa657;">{_esc(pq)}</code>'
        '</div>'
    )


def _apply_facts_local(g, facts_src: str) -> Dict[str, Any]:
    """Apply Prolog facts to the graph through the LOCAL KnowledgeGraph.

    Does not use apply_facts_to_graph from nl2prolog.dialog — that one
    tries to import KnowledgeGraph from its own package and fails
    with 'NoneType' object has no attribute 'from_prolog'.

    Returns dict: {nodes, edges, attributes} or {error: str}.
    Unknown predicates (user_condition/1, true_condition/1, …) are
    silently ignored — same as in the old dialog.apply_facts_to_graph.
    """
    if not facts_src or not facts_src.strip():
        return {"nodes": 0, "edges": 0, "attributes": 0}
    try:
        new_g = KnowledgeGraph.from_prolog(facts_src)
    except Exception as ex:
        return {"error": f"parse: {ex}"}
    try:
        for n in new_g.nodes.values():
            g.add_node(n.id, n.type, n.props)
        for e in new_g.edges:
            g.add_edge(e.source, e.target, e.predicate)
        for a in new_g.attributes:
            g.add_attribute(a.entity, a.name, a.value)
    except Exception as ex:
        return {"error": f"merge: {ex}"}
    return {
        "nodes": len(new_g.nodes),
        "edges": len(new_g.edges),
        "attributes": len(new_g.attributes),
    }


def _dialog_apply_facts(g, facts: str, status: str,
                        lang: str = "en") -> str:
    if not facts or apply_facts_to_graph is None:
        return status
    try:
        _, summary = apply_facts_to_graph(g, facts)
    except Exception as ex:
        return status + t(lang, "dialog_facts_err", e=ex)

    if isinstance(summary, dict) and "error" in summary:
        return status + t(lang, "dialog_facts_err",
                           e=summary['error'])

    n = (summary or {}).get("nodes", 0)
    e = (summary or {}).get("edges", 0)
    a = (summary or {}).get("attributes", 0)
    if n or e or a:
        return status + t(lang, "dialog_facts_added", n=n, e=e, a=a)
    return status


def _dialog_hint_for_no_solution(result, dlg_state,
                                 lang: str = "en") -> str:
    """Hint if a pending question exists but no solution is found."""
    if not isinstance(result, dict):
        return ""
    if not getattr(dlg_state, 'pending_query', ''):
        return ""

    # Explicit "no solution": key "result" present and False / None.
    # Do not confuse with success: on success there is no "result" key,
    # only a non-empty "solutions" — then .get("result") would also be
    # None, and this used to trigger falsely (v5.13.0 bug).
    if "result" in result and result["result"] is False:
        return t(lang, "dialog_no_solution_hint")
    if "result" in result and result["result"] is None:
        return t(lang, "dialog_no_solution_hint")

    # Fallback: solutions is an empty list (should not happen, but safe)
    sols = result.get("solutions")
    if isinstance(sols, list) and len(sols) == 0:
        return t(lang, "dialog_no_solution_hint")

    return ""


# =====================================================================
# Dialog handlers
# =====================================================================
def h_dialog_ask(g, text, t2p_cls, dlg_state, lang: str = "en"):
    """NL question / statement through DialogTurn.ask()."""
    g = _safe(g)
    text = (text or "").strip()
    cur_t = _dialog_transcript_str(dlg_state, lang)
    cur_p = _dialog_pending_html(dlg_state, lang)

    if not text:
        return (g, dlg_state, {},
                _status_html(t(lang, "dialog_empty_input")), cur_t, cur_p)

    if not _DIALOG_OK:
        return (g, dlg_state, {"error": "dialog unavailable"},
                _status_html(t(lang, "dialog_unavailable_short")),
                cur_t, cur_p)

    if dlg_state is None:
        dlg_state = _dialog_init(t2p_cls)
        if dlg_state is None:
            return (g, dlg_state, {"error": "cannot init"},
                    _status_html(t(lang, "dialog_init_failed")),
                    cur_t, cur_p)

    try:
        result, status = dlg_state.ask(g, text)
    except Exception as e:
        return (g, dlg_state, {"error": str(e)},
                _status_html(f"✗ {e}"),
                _dialog_transcript_str(dlg_state, lang),
                _dialog_pending_html(dlg_state, lang))

    # Not a question — apply extracted facts to the graph
    if isinstance(result, dict) and result.get("is_question") is False:
        facts = result.get("facts_extracted", "")
        status = _dialog_apply_facts(g, facts, status, lang)
        # The parser returned an empty query from the question — warn
        if text.strip().endswith("?") and not (
            isinstance(result.get("solutions"), list)
            and result["solutions"]
        ):
            status += t(lang, "dialog_unrecognized")

    status += _dialog_hint_for_no_solution(result, dlg_state, lang)

    return (g, dlg_state, result, _status_html(status),
            _dialog_transcript_str(dlg_state, lang),
            _dialog_pending_html(dlg_state, lang))


def h_dialog_answer(g, text, t2p_cls, dlg_state, lang: str = "en"):
    """NL answer to the pending question via DialogTurn.answer()."""
    g = _safe(g)
    text = (text or "").strip()
    cur_t = _dialog_transcript_str(dlg_state, lang)
    cur_p = _dialog_pending_html(dlg_state, lang)

    if not text:
        return (g, dlg_state, {},
                _status_html(t(lang, "dialog_empty_answer")), cur_t, cur_p)

    if not _DIALOG_OK or dlg_state is None:
        return (g, dlg_state, {"error": "dialog not initialized"},
                _status_html(t(lang, "dialog_not_initialized")),
                cur_t, cur_p)

    try:
        facts, status = dlg_state.answer(g, text)
    except Exception as e:
        return (g, dlg_state, {"error": str(e)},
                _status_html(f"✗ {e}"),
                _dialog_transcript_str(dlg_state, lang),
                _dialog_pending_html(dlg_state, lang))

    status = _dialog_apply_facts(g, facts, status, lang)

    return (g, dlg_state, {"facts": facts} if facts else {},
            _status_html(status),
            _dialog_transcript_str(dlg_state, lang),
            _dialog_pending_html(dlg_state, lang))


def h_dialog_yes(g, t2p_cls, dlg_state, lang: str = "en"):
    if dlg_state is None or not getattr(dlg_state, 'pending_query', ''):
        return (g, dlg_state, {},
                _status_html(t(lang, "dialog_no_pending")),
                _dialog_transcript_str(dlg_state, lang),
                _dialog_pending_html(dlg_state, lang))
    return h_dialog_answer(g, "да", t2p_cls, dlg_state, lang)


def h_dialog_no(g, t2p_cls, dlg_state, lang: str = "en"):
    if dlg_state is None or not getattr(dlg_state, 'pending_query', ''):
        return (g, dlg_state, {},
                _status_html(t(lang, "dialog_no_pending")),
                _dialog_transcript_str(dlg_state, lang),
                _dialog_pending_html(dlg_state, lang))
    return h_dialog_answer(g, "нет", t2p_cls, dlg_state, lang)


def h_dialog_reset(g, dlg_state, lang: str = "en"):
    if dlg_state is not None and hasattr(dlg_state, 'reset'):
        try:
            dlg_state.reset()
        except Exception:
            pass
    return (dlg_state,
            _status_html(t(lang, "dialog_reset_ok")),
            _dialog_transcript_str(dlg_state, lang),
            _dialog_pending_html(dlg_state, lang))


# =====================================================================
# UI
# =====================================================================
def build_ui() -> gr.Blocks:
    lang = _detect_system_lang()
    print(f"[kg-editor] language: {lang} "
          f"({t(lang, 'lang_override_hint')})",
          file=_sys.stderr, flush=True)

    _blocks_kwargs = {"title": t(lang, "title")}
    if not _LAUNCH_THEME:
        _blocks_kwargs.update(
            css=_GLOBAL_CSS,
            theme=_make_theme(),
            head=_DARK_FORCE_HEAD,
        )

    with gr.Blocks(**_blocks_kwargs) as ui:
        graph_state = gr.State(KnowledgeGraph())
        current_path = gr.State("")
        t2p_cls_state = gr.State(None)
        nl_text_state = gr.State("")

        sel_node_id = gr.State("")
        sel_edge_idx = gr.State("")
        dlg_state = gr.State(None)
        lang_state = gr.State(lang)

        with gr.Row(equal_height=False):
            # COLUMN 1
            with gr.Column(scale=2, min_width=300):
                gr.HTML(
                    f'<div class="col-head">{t(lang, "col_project")}</div>')
                with gr.Row(equal_height=True):
                    open_btn = gr.Button(
                        t(lang, "btn_open"), size="sm",
                        elem_classes=["compact-btn"])
                    merge_btn = gr.Button(
                        t(lang, "btn_merge"), size="sm",
                        elem_classes=["compact-btn"])
                    new_btn = gr.Button(
                        t(lang, "btn_new"), size="sm",
                        elem_classes=["compact-btn"])
                    save_btn = gr.Button(
                        t(lang, "btn_save"), size="sm",
                        elem_classes=["compact-btn"])
                    example_btn = gr.Button(
                        t(lang, "btn_example"), size="sm", scale=0,
                        elem_classes=["compact-btn"])

                stats_html = gr.HTML(_stats_html(KnowledgeGraph(), lang))
                project_status = gr.HTML(_status_html(""))

                with gr.Accordion(t(lang, "nl_import_title"), open=False):
                    nl_package_status = gr.HTML(
                        _nl_package_status_html(lang))

                    text_file_input = gr.File(
                        label=t(lang, "nl_file_label"),
                        file_types=[".txt", ".pdf", ".docx", ".fb2"],
                        elem_classes=["compact-file"])
                    file_status = gr.HTML("")
                    open_modal_btn = gr.Button(
                        t(lang, "nl_open_text_btn"), size="sm",
                        visible=False,
                        elem_classes=["compact-btn"])

                    nl_text = gr.Textbox(
                        label=t(lang, "nl_short_text_label"), lines=3,
                        elem_classes=["compact-tb"])
                    with gr.Row(equal_height=True,
                                elem_classes=["nowrap-row"]):
                        btn_full_graph = gr.Button(
                            t(lang, "nl_btn_facts"), size="sm",
                            scale=1, min_width=0,
                            elem_classes=["compact-btn"],
                            variant="primary")
                        btn_extract_query = gr.Button(
                            t(lang, "nl_btn_query"), size="sm",
                            scale=1, min_width=0,
                            elem_classes=["compact-btn"])
                        clear_text_btn = gr.Button(
                            t(lang, "nl_btn_clear"), size="sm",
                            scale=0, min_width=0,
                            elem_classes=["compact-btn"])

                    log_filtered_cb = gr.Checkbox(
                        label=t(lang, "nl_log_filtered"), value=True)
                    nl_status = gr.HTML(
                        _status_html(t(lang, "nl_status_ready")))

                    with gr.Accordion(
                        t(lang, "custom_conv_title"),
                        open=not _T2P_OK,
                    ):
                        t2p_path_in = gr.Textbox(
                            placeholder=t(lang, "t2p_path_placeholder"),
                            show_label=False, lines=1,
                            elem_classes=["compact-tb"])
                        with gr.Row(equal_height=True):
                            t2p_pick_btn = gr.Button(
                                t(lang, "t2p_pick"), size="sm",
                                elem_classes=["compact-btn"])
                            t2p_load_btn = gr.Button(
                                t(lang, "t2p_load"), size="sm",
                                elem_classes=["compact-btn"])
                            t2p_reset_btn = gr.Button(
                                t(lang, "t2p_reset"), size="sm",
                                elem_classes=["compact-btn"])
                        t2p_status = gr.HTML(_status_html(
                            t(lang, "t2p_status_builtin") if _T2P_OK
                            else t(lang, "t2p_status_unavailable")))

                with gr.Accordion(t(lang, "imp_prolog_title"), open=False):
                    import_code = gr.Code(
                        language=None, lines=8,
                        value=t(lang, "paste_prolog"))
                    import_btn = gr.Button(
                        t(lang, "imp_prolog_btn"), size="sm",
                        elem_classes=["compact-btn"])

                with gr.Accordion(t(lang, "diag_title"), open=False):
                    diag_btn = gr.Button(
                        t(lang, "diag_show"), size="sm",
                        elem_classes=["compact-btn"])
                    diag_json = gr.JSON(label="", show_label=False)

            # COLUMN 2
            with gr.Column(scale=5, min_width=500):
                gr.HTML(
                    f'<div class="col-head">{t(lang, "col_editor")}</div>')

                with gr.Tabs():
                    with gr.Tab(t(lang, "tab_nodes")):
                        nodes_tbl = gr.Dataframe(
                            headers=t(lang, "nodes_headers"),
                            datatype=["str", "html", "str"],
                            type="array",
                            interactive=False,
                            wrap=True,
                            elem_classes=["compact-table"])
                        with gr.Row(equal_height=True):
                            nid_in = gr.Textbox(
                                placeholder=t(lang, "nodes_id_placeholder"),
                                show_label=False, scale=2,
                                elem_classes=["compact-tb"])
                            ntype_in = gr.Textbox(
                                placeholder=t(lang,
                                            "nodes_type_placeholder"),
                                show_label=False, scale=2,
                                elem_classes=["compact-tb"])
                            add_node_btn = gr.Button(
                                t(lang, "nodes_add_btn"), size="sm",
                                scale=1, min_width=0,
                                elem_classes=["compact-btn"])

                        with gr.Row(equal_height=True):
                            edit_node_id_in = gr.Textbox(
                                placeholder=t(lang,
                                            "nodes_edit_id_placeholder"),
                                show_label=False, scale=2,
                                elem_classes=["compact-tb"])
                            edit_node_type_in = gr.Textbox(
                                placeholder=t(lang,
                                            "nodes_edit_type_placeholder"),
                                show_label=False, scale=2,
                                elem_classes=["compact-tb"])
                            edit_node_btn = gr.Button(
                                t(lang, "nodes_edit_btn"), size="sm",
                                scale=1, min_width=0,
                                elem_classes=["compact-btn"])
                            del_node_btn = gr.Button(
                                t(lang, "nodes_del_btn"), size="sm",
                                scale=1, min_width=0,
                                elem_classes=["compact-btn"])

                        node_msg = gr.Textbox(
                            label="", show_label=False, interactive=False,
                            lines=1, elem_classes=["compact-tb"])

                    with gr.Tab(t(lang, "tab_edges")):
                        edges_tbl = gr.Dataframe(
                            headers=t(lang, "edges_headers"),
                            datatype=["str", "html", "html", "html"],
                            type="array",
                            interactive=False,
                            wrap=True,
                            elem_classes=["compact-table"])
                        with gr.Row(equal_height=True):
                            esrc_in = gr.Textbox(
                                placeholder=t(lang,
                                            "edges_src_placeholder"),
                                show_label=False,
                                scale=2, elem_classes=["compact-tb"])
                            etgt_in = gr.Textbox(
                                placeholder=t(lang,
                                            "edges_tgt_placeholder"),
                                show_label=False,
                                scale=2, elem_classes=["compact-tb"])
                            epred_in = gr.Textbox(
                                placeholder=t(lang,
                                            "edges_pred_placeholder"),
                                show_label=False,
                                scale=2, elem_classes=["compact-tb"])
                            add_edge_btn = gr.Button(
                                t(lang, "edges_add_btn"), size="sm",
                                scale=1, min_width=0,
                                elem_classes=["compact-btn"])

                        with gr.Row(equal_height=True):
                            edit_edge_src_in = gr.Textbox(
                                placeholder=t(lang,
                                            "edges_edit_src_placeholder"),
                                show_label=False,
                                scale=2, elem_classes=["compact-tb"])
                            edit_edge_tgt_in = gr.Textbox(
                                placeholder=t(lang,
                                            "edges_edit_tgt_placeholder"),
                                show_label=False,
                                scale=2, elem_classes=["compact-tb"])
                            edit_edge_pred_in = gr.Textbox(
                                placeholder=t(lang,
                                            "edges_edit_pred_placeholder"),
                                show_label=False,
                                scale=2, elem_classes=["compact-tb"])
                            edit_edge_btn = gr.Button(
                                t(lang, "edges_edit_btn"), size="sm",
                                scale=1, min_width=0,
                                elem_classes=["compact-btn"])
                            del_edge_btn = gr.Button(
                                t(lang, "edges_del_btn"), size="sm",
                                scale=1, min_width=0,
                                elem_classes=["compact-btn"])

                        edge_msg = gr.Textbox(
                            label="", show_label=False, interactive=False,
                            lines=1, elem_classes=["compact-tb"])

                    with gr.Tab(t(lang, "tab_attrs")):
                        attrs_tbl = gr.HTML(
                            _attrs_html(KnowledgeGraph(), lang))
                        with gr.Row(equal_height=True):
                            aent_in = gr.Textbox(
                                placeholder=t(lang,
                                            "attrs_ent_placeholder"),
                                show_label=False,
                                scale=2, elem_classes=["compact-tb"])
                            aname_in = gr.Textbox(
                                placeholder=t(lang,
                                            "attrs_name_placeholder"),
                                show_label=False,
                                scale=2, elem_classes=["compact-tb"])
                            aval_in = gr.Textbox(
                                placeholder=t(lang,
                                            "attrs_value_placeholder"),
                                show_label=False,
                                scale=2, elem_classes=["compact-tb"])
                            add_attr_btn = gr.Button(
                                t(lang, "attrs_add_btn"), size="sm",
                                scale=1, min_width=0,
                                elem_classes=["compact-btn"])
                        with gr.Row(equal_height=True):
                            del_attr_dd = gr.Dropdown(
                                choices=[],
                                label=t(lang, "attrs_del_placeholder"),
                                show_label=False, scale=4)
                            del_attr_btn = gr.Button(
                                t(lang, "attrs_del_btn"), size="sm",
                                scale=1, min_width=0,
                                elem_classes=["compact-btn"])
                        attr_msg = gr.Textbox(
                            label="", show_label=False, interactive=False,
                            lines=1, elem_classes=["compact-tb"])

                    with gr.Tab(t(lang, "tab_filtered")):
                        filtered_tbl = gr.HTML(
                            _empty_table_html(t(lang, "filtered_empty")))

                    with gr.Tab(t(lang, "tab_dialog")):
                        if not _DIALOG_OK:
                            gr.HTML(_dialog_unavailable_banner(lang))

                        with gr.Column(visible=_DIALOG_OK):
                            gr.HTML(
                                '<div style="font-size:11px;color:#8b949e;'
                                'margin-bottom:6px;line-height:1.5;">'
                                f'{t(lang, "dialog_help")}'
                                '</div>'
                            )

                            dialog_pending = gr.HTML(_empty_table_html(
                                t(lang, "dialog_not_started")))

                            dlg_text = gr.Textbox(
                                label="", show_label=False,
                                placeholder=t(lang,
                                              "dialog_text_placeholder"),
                                lines=3, elem_classes=["compact-tb"])

                            with gr.Row(equal_height=True):
                                dlg_ask_btn = gr.Button(
                                    t(lang, "dialog_ask"), size="sm",
                                    scale=1, min_width=0,
                                    elem_classes=["compact-btn"],
                                    variant="primary")
                                dlg_answer_btn = gr.Button(
                                    t(lang, "dialog_answer"), size="sm",
                                    scale=1, min_width=0,
                                    elem_classes=["compact-btn"])
                                dlg_yes_btn = gr.Button(
                                    t(lang, "dialog_yes"), size="sm",
                                    scale=0, min_width=0,
                                    elem_classes=["compact-btn"])
                                dlg_no_btn = gr.Button(
                                    t(lang, "dialog_no"), size="sm",
                                    scale=0, min_width=0,
                                    elem_classes=["compact-btn"])
                                dlg_reset_btn = gr.Button(
                                    t(lang, "dialog_reset"), size="sm",
                                    scale=0, min_width=0,
                                    elem_classes=["compact-btn"])

                            dlg_status_html = gr.HTML(
                                _status_html(t(lang, "dialog_status_ready")))
                            dlg_result = gr.JSON(label="", show_label=False)

                            gr.HTML(
                                f'<div class="col-head">'
                                f'{t(lang, "dialog_transcript_head")}'
                                f'</div>')
                            dlg_transcript_box = gr.Textbox(
                                label="", show_label=False,
                                interactive=False, lines=10,
                                value=t(lang, "dialog_transcript_none"),
                                elem_classes=["compact-tb"])

                    with gr.Tab(t(lang, "tab_source")):
                        src_preview = gr.HTML(_prolog_code_html("", lang))
                        with gr.Accordion(t(lang, "src_edit_accordion"),
                                          open=False):
                            src_code = gr.Code(
                                language=None, lines=18,
                                value=t(lang, "src_code_placeholder"))
                        with gr.Row(equal_height=True):
                            serialize_btn = gr.Button(
                                t(lang, "src_refresh_btn"), size="sm",
                                elem_classes=["compact-btn"])
                            parse_src_btn = gr.Button(
                                t(lang, "src_apply_btn"), size="sm",
                                elem_classes=["compact-btn"])
                        src_status = gr.HTML(
                            _status_html(t(lang, "src_ready")))

            # COLUMN 3
            with gr.Column(scale=4, min_width=420):
                gr.HTML(
                    f'<div class="col-head">{t(lang, "col_visual")}</div>')
                graph_html = gr.HTML(render_pyvis(None))

                gr.HTML(
                    f'<div class="col-head">{t(lang, "col_queries")}</div>')
                query_in = gr.Textbox(
                    placeholder=t(lang, "query_placeholder"), lines=3,
                    show_label=False, elem_classes=["compact-tb"])
                with gr.Row(equal_height=True):
                    run_q_btn = gr.Button(
                        t(lang, "query_run_btn"), size="sm",
                        elem_classes=["compact-btn"])
                    help_btn = gr.Button(
                        t(lang, "query_help_btn"), size="sm",
                        elem_classes=["compact-btn"])

                query_status = gr.Textbox(
                    label="", show_label=False, interactive=False,
                    lines=1, elem_classes=["compact-tb"])
                query_out = gr.JSON(label="Solutions", show_label=False)

                if not _AGENT_OK:
                    gr.Markdown(t(lang, "query_agent_not_loaded"))

        # Modal window
        with gr.Column(visible=False,
                       elem_classes=["modal-overlay"]) as modal_col:
            with gr.Column(elem_classes=["modal-content"]):
                gr.HTML('<div class="col-head">📄 Text</div>')
                modal_text = gr.Textbox(
                    lines=20, show_label=False,
                    elem_classes=["modal-textarea"])
                with gr.Row():
                    modal_apply_btn = gr.Button(
                        "✅ Apply", size="sm", variant="primary")
                    modal_cancel_btn = gr.Button(
                        "❌ Cancel", size="sm")

        # =================================================================
        # Wiring
        # =================================================================
        refresh_outs = [
            graph_state, nodes_tbl, edges_tbl, attrs_tbl,
            stats_html, graph_html,
        ]

        # Converter settings
        t2p_pick_btn.click(_h_pick_t2p, [], [t2p_path_in])

        t2p_load_btn.click(
            h_load_t2p_module, [t2p_path_in, lang_state],
            [t2p_cls_state, t2p_status],
        ).then(
            lambda c, l: _nl_package_status_html(l, t2p_custom=(c is not None)),
            [t2p_cls_state, lang_state],
            [nl_package_status],
        ).then(
            lambda: None, [], [dlg_state],
        )

        t2p_reset_btn.click(
            lambda l: (None, _status_html(t(l, "t2p_reset_done"))),
            [lang_state],
            [t2p_cls_state, t2p_status],
        ).then(
            lambda l: _nl_package_status_html(l),
            [lang_state],
            [nl_package_status],
        ).then(
            lambda: None, [], [dlg_state],
        )

        # NL import
        text_file_input.upload(
            h_load_text_file, [text_file_input, lang_state],
            [nl_text_state, file_status, open_modal_btn, modal_col])
        open_modal_btn.click(
            h_open_modal, [nl_text_state], [modal_col, modal_text])
        modal_apply_btn.click(
            h_apply_modal, [modal_text, lang_state],
            [modal_col, nl_text_state, file_status])
        modal_cancel_btn.click(
            lambda: gr.update(visible=False), [], [modal_col])
        clear_text_btn.click(
            h_clear_nl, [lang_state],
            [nl_text, nl_text_state, file_status, open_modal_btn, modal_col])

        btn_full_graph.click(
            h_import_full_graph,
            [graph_state, nl_text, nl_text_state, t2p_cls_state,
             log_filtered_cb, lang_state],
            [nl_status, graph_state, filtered_tbl],
        ).then(
            lambda g, l: _refresh(g, l), [graph_state, lang_state],
            refresh_outs)

        btn_extract_query.click(
            h_extract_query,
            [nl_text, nl_text_state, t2p_cls_state, lang_state],
            [query_in, nl_status])

        import_btn.click(
            h_parse_source, [graph_state, import_code, lang_state],
            [graph_state, src_status],
        ).then(
            lambda g, l: _refresh(g, l), [graph_state, lang_state],
            refresh_outs)

        # Project
        open_btn.click(
            h_open_file, [graph_state, lang_state],
            refresh_outs + [project_status],
        ).then(
            _serialize_and_preview, [graph_state, lang_state],
            [src_code, src_preview],
        ).then(
            lambda: None, [], [dlg_state],
        )
        new_btn.click(
            h_new_project, [graph_state, lang_state],
            refresh_outs + [project_status],
        ).then(
            _serialize_and_preview, [graph_state, lang_state],
            [src_code, src_preview],
        ).then(
            lambda: None, [], [dlg_state],
        )
        example_btn.click(
            h_load_example, [graph_state, lang_state],
            refresh_outs + [project_status],
        ).then(
            _serialize_and_preview, [graph_state, lang_state],
            [src_code, src_preview],
        ).then(
            lambda: None, [], [dlg_state],
        )
        merge_btn.click(
            h_merge_file, [graph_state, lang_state],
            refresh_outs + [project_status],
        ).then(
            _serialize_and_preview, [graph_state, lang_state],
            [src_code, src_preview],
        )
        # dlg_state is NOT reset: merge is additive, the current dialog
        # remains valid. If the user wants a clean dialog — press 🗑️
        # on the "💬 Dialog" tab.
        save_btn.click(
            h_save_file, [graph_state, current_path, lang_state],
            [project_status, current_path])

        # Nodes
        add_node_btn.click(
            h_add_node, [graph_state, nid_in, ntype_in, lang_state],
            refresh_outs + [nid_in, node_msg])

        nodes_tbl.select(
            h_select_node, [graph_state],
            [edit_node_id_in, edit_node_type_in, sel_node_id])

        edit_node_btn.click(
            h_edit_node,
            [graph_state, sel_node_id, edit_node_id_in,
             edit_node_type_in, lang_state],
            refresh_outs + [node_msg])

        del_node_btn.click(
            h_del_node_selected, [graph_state, sel_node_id, lang_state],
            refresh_outs + [node_msg])

        # Edges
        add_edge_btn.click(
            h_add_edge, [graph_state, esrc_in, etgt_in, epred_in,
                         lang_state],
            refresh_outs + [esrc_in, etgt_in, edge_msg])

        edges_tbl.select(
            h_select_edge, [graph_state],
            [edit_edge_src_in, edit_edge_tgt_in, edit_edge_pred_in,
             sel_edge_idx])

        edit_edge_btn.click(
            h_edit_edge,
            [graph_state, sel_edge_idx, edit_edge_src_in,
             edit_edge_tgt_in, edit_edge_pred_in, lang_state],
            refresh_outs + [edge_msg])

        del_edge_btn.click(
            h_del_edge_selected, [graph_state, sel_edge_idx, lang_state],
            refresh_outs + [edge_msg])

        # Attributes
        add_attr_btn.click(
            h_add_attr, [graph_state, aent_in, aname_in, aval_in,
                         lang_state],
            refresh_outs + [aent_in, aname_in, attr_msg])
        del_attr_btn.click(
            h_del_attr, [graph_state, del_attr_dd, lang_state],
            refresh_outs)

        # Prolog Source
        serialize_btn.click(
            _serialize_and_preview, [graph_state, lang_state],
            [src_code, src_preview])
        src_code.change(
            lambda s, l: _prolog_code_html(s or "", l),
            [src_code, lang_state], [src_preview])
        parse_src_btn.click(
            h_parse_source, [graph_state, src_code, lang_state],
            [graph_state, src_status],
        ).then(
            lambda g, l: _refresh(g, l), [graph_state, lang_state],
            refresh_outs)

        # Queries
        run_q_btn.click(
            h_query, [graph_state, query_in, lang_state],
            [query_out, query_status])
        help_btn.click(
            lambda l: _status_html(t(l, "query_help_text")),
            [lang_state], [query_status])

        # Dialog
        _dialog_outputs = [
            graph_state, dlg_state, dlg_result, dlg_status_html,
            dlg_transcript_box, dialog_pending,
        ]

        dlg_ask_btn.click(
            h_dialog_ask,
            [graph_state, dlg_text, t2p_cls_state, dlg_state, lang_state],
            _dialog_outputs,
        ).then(
            lambda g, l: _refresh(g, l), [graph_state, lang_state],
            refresh_outs)

        dlg_answer_btn.click(
            h_dialog_answer,
            [graph_state, dlg_text, t2p_cls_state, dlg_state, lang_state],
            _dialog_outputs,
        ).then(
            lambda g, l: _refresh(g, l), [graph_state, lang_state],
            refresh_outs)

        dlg_yes_btn.click(
            h_dialog_yes,
            [graph_state, t2p_cls_state, dlg_state, lang_state],
            _dialog_outputs,
        ).then(
            lambda g, l: _refresh(g, l), [graph_state, lang_state],
            refresh_outs)

        dlg_no_btn.click(
            h_dialog_no,
            [graph_state, t2p_cls_state, dlg_state, lang_state],
            _dialog_outputs,
        ).then(
            lambda g, l: _refresh(g, l), [graph_state, lang_state],
            refresh_outs)

        dlg_reset_btn.click(
            h_dialog_reset,
            [graph_state, dlg_state, lang_state],
            [dlg_state, dlg_status_html, dlg_transcript_box,
             dialog_pending],
        )

        # Diagnostics
        diag_btn.click(
            lambda g, c, ds: {
                "summary": _safe(g).summary(),
                "pyagent": _AGENT_OK,
                "t2p_ok": _T2P_OK,
                "nl2prolog_ok": _NL2PROLOG_OK,
                "nl2prolog_version": _NL2PROLOG_VERSION,
                "t2p_custom": c is not None,
                "dialog_ok": _DIALOG_OK,
                "dialog_active": ds is not None,
                "dialog_pending": bool(
                    getattr(ds, 'pending_query', '') if ds else False
                ),
            },
            [graph_state, t2p_cls_state, dlg_state],
            [diag_json])

        return ui


def launch(share: bool = False, host: str = "127.0.0.1", port: int = 7861,
           inbrowser: bool = True, **kwargs) -> None:
    ui = build_ui()
    launch_kwargs = dict(
        share=share, server_name=host, server_port=port,
        inbrowser=inbrowser)

    _here = os.path.dirname(os.path.abspath(__file__))
    for subdir in ("", "assets"):
        for name in ("favicon.png", "favicon.ico", "favicon.svg"):
            path = (os.path.join(_here, subdir, name)
                    if subdir else os.path.join(_here, name))
            if os.path.isfile(path):
                launch_kwargs["favicon_path"] = path
                break

    if _LAUNCH_THEME:
        launch_kwargs.update(
            theme=_make_theme(),
            css=_GLOBAL_CSS,
            head=_DARK_FORCE_HEAD,
        )
    launch_kwargs.update(kwargs)
    ui.launch(**launch_kwargs)


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7861)
    parser.add_argument("--share", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    launch(host=args.host, port=args.port, share=args.share,
           inbrowser=not args.no_browser)


if __name__ == "__main__":
    main()