"""dialog.py — Диалоговый контекст для Q&A через TextToProlog + PyAgentProlog.

v5.11.20: coreference («ему», «он» → last_entity) и эллипсис
(«А у X?» → replace entity in last_query). Разрешает 4 dialog-turn
из dlg_001.json без изменения text_to_prolog.py.

Использование:
    dlg = DialogTurn(t2p=TextToProlog(), agent_factory=Agent)
    answer, status = dlg.ask(g, "Кто директор технопарка Саратов?")
    answer, status = dlg.ask(g, "А сколько ему лет?")   # → иванов_иван, 45
    answer, status = dlg.ask(g, "А где он работает?")    # → работать_в
    answer, status = dlg.ask(g, "Какая площадь у технопарка Москва?")
    answer, status = dlg.ask(g, "А у Казани?")           # → технопарк_казань
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


# Предлоги, приклеиваемые к глаголу в зависимости от wh-locative.
_LOCATIVE_SUFFIX = {
    'где': 'в',
    'куда': 'в',
    'откуда': 'из',
}

# Кэш лемм (ускоряет повторные _lemma в одном диалоге).
_LEMMA_CACHE: Dict[str, str] = {}
_MORPH = None


def _get_morph():
    global _MORPH
    if _MORPH is None:
        try:
            from pymorphy3 import MorphAnalyzer
            _MORPH = MorphAnalyzer()
        except Exception:
            _MORPH = False
    return _MORPH if _MORPH is not False else None


@dataclass
class DialogTurn:
    """Состояние диалога: pending question + контекст coref/ellipsis."""

    t2p: Any = None
    agent_factory: Optional[Callable] = None
    solution_limit: int = 1000

    # --- Pending (вопрос ждёт ответа) ---
    pending_query: str = ""
    pending_facts: str = ""
    pending_question_text: str = ""

    # --- Context (для coreference / ellipsis) — переживает ходы ---
    last_entity: str = ""        # последний sole solution (иванов_иван)
    last_query: str = ""         # последний успешно исполненный query

    history: List[Dict[str, Any]] = field(default_factory=list)

    # ==================================================================
    # Морфология
    # ==================================================================
    def _lemma(self, word: str) -> str:
        """Лемматизация: t2p → pymorphy3 → lowercase."""
        w = (word or '').lower().strip()
        if not w:
            return ''
        if w in _LEMMA_CACHE:
            return _LEMMA_CACHE[w]

        # 1. через t2p
        if self.t2p and hasattr(self.t2p, '_lemma_word'):
            try:
                result = self.t2p._lemma_word(word) or w
                _LEMMA_CACHE[w] = result
                return result
            except Exception:
                pass

        # 2. напрямую через pymorphy3
        morph = _get_morph()
        if morph is not None:
            try:
                parses = morph.parse(w)
                if parses and parses[0].normal_form:
                    result = parses[0].normal_form
                    _LEMMA_CACHE[w] = result
                    return result
            except Exception:
                pass

        _LEMMA_CACHE[w] = w
        return w

    # ==================================================================
    # Resolution: ellipsis
    # ==================================================================
    def _replace_entity_in_atom(
        self, atom: str, new_place_lemma: str,
    ) -> str:
        """'технопарк_москва' + 'казань' → 'технопарк_казань'."""
        if not atom or not new_place_lemma:
            return ""
        parts = atom.split('_')
        if len(parts) < 2:
            return ""
        prefix = '_'.join(parts[:-1])
        return f"{prefix}_{new_place_lemma}"

    def _resolve_ellipsis(self, nl: str) -> Tuple[str, bool]:
        """«А у X?» → repeat last_query structure with X substituted.

        Returns (query, is_resolved).
        """
        if not self.last_query:
            return "", False

        nl_stripped = nl.strip().rstrip('?').strip()

        # «А у X?»
        m = re.match(
            r'^[Аа]\s+[Уу]\s+([А-ЯЁA-Z][а-яёa-z]+)\s*$',
            nl_stripped,
        )
        if not m:
            return "", False

        place_surface = m.group(1)
        place_lemma = self._lemma(place_surface)
        if not place_lemma:
            return "", False

        query = self.last_query.strip()

        # attribute('subj', 'key', var)
        am = re.match(
            r"attribute\('([^']+)',\s*'([^']+)',\s*(\w+)\)$",
            query,
        )
        if am:
            subj, key, var = am.groups()
            new_subj = self._replace_entity_in_atom(subj, place_lemma)
            if new_subj:
                return f"attribute('{new_subj}', '{key}', {var})", True

        # edge(X, 'obj', 'pred')  или  edge('subj', 'obj', 'pred')
        em = re.match(
            r"edge\((X|[^,]+),\s*'([^']+)',\s*'([^']+)'\)$",
            query,
        )
        if em:
            subj, obj, pred = em.groups()
            if subj == "X":
                new_obj = self._replace_entity_in_atom(obj, place_lemma)
                if new_obj:
                    return f"edge(X, '{new_obj}', '{pred}')", True
            else:
                new_subj = self._replace_entity_in_atom(subj, place_lemma)
                if new_subj:
                    return f"edge('{new_subj}', '{obj}', '{pred}')", True

        return "", False

    # ==================================================================
    # Resolution: coreference
    # ==================================================================
    def _resolve_coreference(self, nl: str) -> Tuple[str, bool]:
        """«А сколько ему лет?» / «А где он работает?» etc.

        Returns (query, is_resolved).
        """
        if not self.last_entity:
            return "", False

        nl_low = nl.strip().rstrip('?').strip().lower()
        # Убираем ведущее "а"
        nl_core = re.sub(r'^а\s+', '', nl_low)
        entity = self.last_entity

        # «сколько ему/ей лет» → attribute(E, 'возраст', X)
        if re.match(
            r'^сколько\s+(?:ему|ей|ним|нему|ней|им)\s+лет$',
            nl_core,
        ):
            return f"attribute('{entity}', 'возраст', X)", True

        # «где/куда/откуда он/она/они <verb>?»
        m = re.match(
            r'^(где|куда|откуда)\s+(?:он|она|оно|они)\s+'
            r'(?:же\s+)?([а-яё]+)$',
            nl_core,
        )
        if m:
            wh = m.group(1)
            verb_surface = m.group(2)
            verb_lemma = self._lemma(verb_surface)
            suffix = _LOCATIVE_SUFFIX.get(wh, 'в')
            return f"edge('{entity}', X, '{verb_lemma}_{suffix}')", True

        # «его/её/их <noun>?» → attribute(E, '<noun>', X)
        m = re.match(r'^(?:его|её|их)\s+([а-яё]+)$', nl_core)
        if m:
            noun_lemma = self._lemma(m.group(1))
            return f"attribute('{entity}', '{noun_lemma}', X)", True

        return "", False

    # ==================================================================
    # Публичный: resolve (coref + ellipsis, без исполнения)
    # ==================================================================
    def resolve(self, nl: str) -> Tuple[str, bool, str]:
        """Разрешить NL как продолжение диалога.

        Returns (query, is_resolved, source_desc).
        Если is_resolved=True, query готов к исполнению.
        """
        # 1. Ellipsis (специфичнее — паттерн «А у X?»)
        q, ok = self._resolve_ellipsis(nl)
        if ok:
            return q, True, f"ellipsis({self.last_query[:40]}…) → {q}"

        # 2. Coreference (местоимения → last_entity)
        q, ok = self._resolve_coreference(nl)
        if ok:
            return q, True, f"coref({self.last_entity}) → {q}"

        return "", False, ""

    # ==================================================================
    # Пользователь задаёт вопрос
    # ==================================================================
    def ask(
        self,
        g,
        text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], str]:
        """NL-вопрос → прогон через Agent → решения.

        v5.11.20: сначала dialog.resolve (coref/ellipsis), потом parse.
        """
        if self.t2p is None:
            return {"error": "TextToProlog не инициализирован"}, "✗"

        text = (text or "").strip()
        if not text:
            return {"result": None}, "✗ Пустой вопрос"

        # v5.11.20: dialog-resolution
        dialog_query, is_resolved, source = self.resolve(text)

        if is_resolved:
            query = dialog_query
            facts = ""
            self.pending_query = query
            self.pending_facts = ""
            self.pending_question_text = text
            self.history.append({
                "role": "user",
                "kind": "question",
                "text": text,
                "query": query,
                "resolved_from": source,
            })
        else:
            facts, query = self.t2p.parse(text)

            # Не вопрос — просто факты
            if not query:
                return (
                    {"facts_extracted": facts, "is_question": False},
                    "ℹ️ Не вопрос — извлечены факты из текста",
                )

            self.pending_query = query
            self.pending_facts = facts
            self.pending_question_text = text
            self.history.append({
                "role": "user",
                "kind": "question",
                "text": text,
                "query": query,
            })

        # Прогон через Agent
        if self.agent_factory is None:
            return (
                {"query": query, "facts": facts},
                f"ℹ️ Запрос сформирован, но Agent недоступен:\n{query}",
            )

        src = self._graph_to_program(g)
        try:
            agent = self.agent_factory(src, context=context or {})
        except Exception as e:
            return (
                {"error": str(e), "query": query},
                f"✗ Ошибка Agent: {e}",
            )

        q = query if query.endswith(".") else query + "."
        sols: List[Any] = []
        try:
            for item in agent.stream(q):
                if isinstance(item, dict) and "error" in item:
                    return (
                        {"error": item["error"], "query": query},
                        f"✗ {item['error']}",
                    )
                if item is False:
                    self.history.append({
                        "role": "system",
                        "kind": "answer",
                        "query": query,
                        "result": False,
                    })
                    self.last_query = query
                    return (
                        {"result": False, "query": query},
                        "✗ Нет решений",
                    )
                if item is True:
                    self.history.append({
                        "role": "system",
                        "kind": "answer",
                        "query": query,
                        "result": True,
                    })
                    self.last_query = query
                    return (
                        {"result": True, "query": query},
                        "✓ true",
                    )
                if isinstance(item, dict):
                    sols.append(item)
                if len(sols) >= self.solution_limit:
                    break
        except Exception as e:
            return (
                {"error": str(e), "query": query},
                f"✗ {e}",
            )

        self.history.append({
            "role": "system",
            "kind": "answer",
            "query": query,
            "solutions": sols,
        })

        # v5.11.20: обновляем контекст
        self.last_query = query
        # last_entity — только для edge/node-запросов (attribute даёт значения)
        if (len(sols) == 1
                and isinstance(sols[0], dict)
                and not query.lstrip().startswith('attribute(')):
            for _k, _v in sols[0].items():
                if isinstance(_v, str) and _v:
                    self.last_entity = _v
                    break

        if not sols:
            return (
                {"result": None, "query": query},
                "Нет решений",
            )
        return (
            {"solutions": sols, "query": query},
            f"✓ {len(sols)} решение(й)",
        )

    # ==================================================================
    # Пользователь отвечает на pending question
    # ==================================================================
    def answer(self, g, text: str) -> Tuple[str, str]:
        if self.t2p is None:
            return "", "✗ TextToProlog не инициализирован"

        text = (text or "").strip()
        if not text:
            return "", "✗ Пустой ответ"

        if not self.pending_query:
            facts, _ = self.t2p.parse(text)
            if facts:
                self.history.append({
                    "role": "user",
                    "kind": "declarative",
                    "text": text,
                    "facts": facts,
                })
            return facts, f"ℹ️ Декларатив (нет pending question). Фактов: {facts.count('.')}"

        try:
            facts = self.t2p.convert_answer(
                text,
                question_condition=self.pending_query,
            )
        except Exception as e:
            return "", f"✗ convert_answer: {e}"

        self.history.append({
            "role": "user",
            "kind": "answer",
            "text": text,
            "facts": facts,
            "for_question": self.pending_question_text,
        })

        self.pending_query = ""
        self.pending_facts = ""
        self.pending_question_text = ""

        if not facts:
            return "", "ℹ️ Ответ не дал фактов"
        return facts, f"✓ Обновлено: {facts.count('.')} факт(ов)"

    def yes(self, g) -> Tuple[str, str]:
        return self.answer(g, "да")

    def no(self, g) -> Tuple[str, str]:
        return self.answer(g, "нет")

    # ==================================================================
    # Сброс / диагностика
    # ==================================================================
    def reset(self) -> None:
        """Сброс pending; context (last_entity/last_query) сохраняется."""
        self.pending_query = ""
        self.pending_facts = ""
        self.pending_question_text = ""

    def reset_context(self) -> None:
        """Полный сброс: pending + context."""
        self.reset()
        self.last_entity = ""
        self.last_query = ""

    def clear_history(self) -> None:
        self.history.clear()

    def transcript(self, n: int = 20) -> str:
        lines: List[str] = []
        for turn in self.history[-n:]:
            role = turn.get("role", "?")
            kind = turn.get("kind", "?")
            text = turn.get("text", "")[:80]
            lines.append(f"[{role}/{kind}] {text}")
            if "query" in turn:
                lines.append(f"    Q: {turn['query'][:80]}")
            if "resolved_from" in turn:
                lines.append(f"    R: {turn['resolved_from']}")
            if "result" in turn:
                lines.append(f"    → {turn['result']}")
            if "facts" in turn:
                lines.append(f"    F: {turn['facts'][:120]}")
        return "\n".join(lines)

    @staticmethod
    def _graph_to_program(g) -> str:
        if g is None:
            return ""
        if hasattr(g, "to_prolog"):
            return (g.to_prolog()
                    + "\nnode(Id, T) :- node(Id, _, T).\n"
                    + "edge(S, T) :- edge(S, T, _).\n")
        return ""


# =====================================================================
# Утилита: применить facts (Prolog-строку) к KnowledgeGraph
# =====================================================================
def apply_facts_to_graph(g, facts_src: str):
    """Добавляет факты из Prolog-строки в граф. Возвращает (graph, summary)."""
    if not facts_src or not facts_src.strip():
        return g, {"nodes": 0, "edges": 0, "attributes": 0}
    try:
        try:
            from .graph_model import KnowledgeGraph
        except ImportError:
            from graph_model import KnowledgeGraph

        new_g = KnowledgeGraph.from_prolog(facts_src)
        for n in new_g.nodes.values():
            g.add_node(n.id, n.type, n.props)
        for e in new_g.edges:
            g.add_edge(e.source, e.target, e.predicate)
        for a in new_g.attributes:
            g.add_attribute(a.entity, a.name, a.value)
        return g, {
            "nodes": len(new_g.nodes),
            "edges": len(new_g.edges),
            "attributes": len(new_g.attributes),
        }
    except Exception as e:
        return g, {"error": str(e)}