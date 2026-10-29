"""dialog.py — Диалоговый контекст для Q&A через TextToProlog + PyAgentProlog.

Использование в app.py:
    from dialog import DialogTurn
    dlg = DialogTurn(t2p=TextToProlog(), agent_factory=Agent)
    answer, status = dlg.ask(g, "У меня есть лицензия?")
    dlg.answer(g, "нет, но есть брокерская")
    dlg.yes(g)  # explicit yes
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class DialogTurn:
    """Состояние диалога: pending question + история."""

    t2p: Any = None  # TextToProlog instance
    agent_factory: Optional[Callable] = None  # Agent class
    solution_limit: int = 1000

    pending_query: str = ""          # Prolog-запрос без завершающей точки
    pending_facts: str = ""          # факты, извлечённые из вопроса
    pending_question_text: str = ""  # исходный NL-вопрос
    history: List[Dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Пользователь задаёт вопрос
    # ------------------------------------------------------------------
    def ask(
        self,
        g,
        text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], str]:
        """NL-вопрос → прогон через Agent → решения.

        Возвращает (answer_dict, status_str).
        Если текст не является вопросом — просто извлекает факты
        и возвращает ({"facts": ...}, "не вопрос").
        """
        if self.t2p is None:
            return {"error": "TextToProlog не инициализирован"}, "✗"

        text = (text or "").strip()
        if not text:
            return {"result": None}, "✗ Пустой вопрос"

        facts, query = self.t2p.parse(text)

        # Не вопрос — пользователь просто предоставил факт
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
        except Exception as e:  # noqa: BLE001
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
                    return (
                        {"result": True, "query": query},
                        "✓ true",
                    )
                if isinstance(item, dict):
                    sols.append(item)
                if len(sols) >= self.solution_limit:
                    break
        except Exception as e:  # noqa: BLE001
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
        if not sols:
            return (
                {"result": None, "query": query},
                "Нет решений",
            )
        return (
            {"solutions": sols, "query": query},
            f"✓ {len(sols)} решение(й)",
        )

    # ------------------------------------------------------------------
    # Пользователь отвечает на pending question
    # ------------------------------------------------------------------
    def answer(
        self,
        g,
        text: str,
    ) -> Tuple[str, str]:
        """NL-ответ → Prolog-факты для обновления KB.

        Возвращает (facts_prolog_str, status_str).
        Если pending_query пуст — просто извлекает факты из ответа.
        """
        if self.t2p is None:
            return "", "✗ TextToProlog не инициализирован"

        text = (text or "").strip()
        if not text:
            return "", "✗ Пустой ответ"

        # Нет pending question — обычный декларатив
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

        # Есть pending question — используем convert_answer
        try:
            facts = self.t2p.convert_answer(
                text,
                question_condition=self.pending_query,
            )
        except Exception as e:  # noqa: BLE001
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

    # ------------------------------------------------------------------
    # Explicit yes/no
    # ------------------------------------------------------------------
    def yes(self, g) -> Tuple[str, str]:
        return self.answer(g, "да")

    def no(self, g) -> Tuple[str, str]:
        return self.answer(g, "нет")

    # ------------------------------------------------------------------
    # Сброс / диагностика
    # ------------------------------------------------------------------
    def reset(self) -> None:
        self.pending_query = ""
        self.pending_facts = ""
        self.pending_question_text = ""
        # history не очищаем — она может быть полезна

    def clear_history(self) -> None:
        self.history.clear()

    def transcript(self, n: int = 20) -> str:
        """Читаемая расшифровка последних n ходов."""
        lines: List[str] = []
        for turn in self.history[-n:]:
            role = turn.get("role", "?")
            kind = turn.get("kind", "?")
            text = turn.get("text", "")[:80]
            lines.append(f"[{role}/{kind}] {text}")
            if "query" in turn:
                lines.append(f"    Q: {turn['query'][:80]}")
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
            return g.to_prolog() + "\nnode(Id, T) :- node(Id, _, T).\nedge(S, T) :- edge(S, T, _).\n"
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
    except Exception as e:  # noqa: BLE001
        return g, {"error": str(e)}