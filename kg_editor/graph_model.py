"""Модель графа знаний + (де)сериализация Prolog.

Формат (совместим с text_to_prolog._to_graph_program):
    node(Id, Props, Type).
    edge(Source, Target, Predicate).
    attribute(Entity, Name, Value).

Идентификаторы по возможности пишутся БЕЗ кавычек (apple). Кавычки — только
если атом не проходит _VALID_ATOM. Значения атрибутов всегда в кавычках.

v5.13: merge() / merge_from_prolog() — аддитивное слияние графов.
        Существующие узлы/рёбра/атрибуты НЕ перезаписываются.

v5.12: fallback на nl2prolog.noise — если пакет установлен, но локального
noise.py нет. Если ничего не установлено — фильтрация отключается,
редактор продолжает работать.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


# ---------------------------------------------------------------- NLP-хелпер
# Приоритет: локальный noise.py → пакет nl2prolog → отключение фильтра.
try:
    from .noise import is_service_word as _is_service_word
except ImportError:
    try:
        from noise import is_service_word as _is_service_word
    except ImportError:
        try:
            from nl2prolog.noise import is_service_word as _is_service_word
        except ImportError:
            _is_service_word = None  # type: ignore


def _default_generic_filter(w: str) -> bool:
    """True, если w — служебное слово и не может быть узлом."""
    if not w:
        return True
    if _is_service_word is None:
        return False

    # Compound-ID (российская_федерация, northern_ireland, …) — это
    # многокомпонентные имена собственные. is_service_word() умеет
    # смотреть только одиночные токены и на compound'ах ошибочно
    # цепляется за первый ADJF-компонент. Не фильтруем их здесь.
    if '_' in w:
        return False

    for lang in ('ru', 'en'):
        try:
            if _is_service_word(w, lang):
                return True
        except Exception:
            pass
    return False


@dataclass
class Node:
    id: str
    type: str = "concept"
    props: Dict[str, str] = field(default_factory=dict)


@dataclass
class Edge:
    source: str
    target: str
    predicate: str


@dataclass
class Attribute:
    entity: str
    name: str
    value: str


class KnowledgeGraph:
    def __init__(
        self,
        generic_filter: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self.nodes: Dict[str, Node] = {}
        self.edges: List[Edge] = []
        self.attributes: List[Attribute] = []
        # Если generic_filter не задан — используем POS-based noise.
        # Передайте `lambda w: False`, чтобы полностью отключить фильтрацию.
        self._generic_filter: Callable[[str], bool] = (
            generic_filter if generic_filter is not None
            else _default_generic_filter
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def add_node(self, node_id: str, node_type: str = "concept",
                 props: Optional[Dict[str, str]] = None) -> Node:
        node_id = (node_id or "").strip()
        if not node_id:
            raise ValueError("id узла пустой")
        if self._generic_filter(node_id):
            raise ValueError(
                f"«{node_id}» — служебное слово (прилагательное, "
                f"местоимение, предлог и т.п.), не может быть узлом графа"
            )
        node_type = (node_type or "concept").strip() or "concept"
        if node_id in self.nodes:
            self.nodes[node_id].type = node_type
            if props:
                self.nodes[node_id].props.update(props)
        else:
            self.nodes[node_id] = Node(node_id, node_type, dict(props or {}))
        return self.nodes[node_id]

    def remove_node(self, node_id: str) -> bool:
        if node_id not in self.nodes:
            return False
        del self.nodes[node_id]
        self.edges = [e for e in self.edges
                      if e.source != node_id and e.target != node_id]
        self.attributes = [a for a in self.attributes if a.entity != node_id]
        return True

    def add_edge(self, source: str, target: str, predicate: str) -> Edge:
        source = (source or "").strip()
        target = (target or "").strip()
        predicate = (predicate or "").strip()
        if not (source and target and predicate):
            raise ValueError("source/target/predicate не могут быть пустыми")
        if self._generic_filter(source):
            raise ValueError(
                f"«{source}» — служебное слово, не может быть source ребра")
        if self._generic_filter(target):
            raise ValueError(
                f"«{target}» — служебное слово, не может быть target ребра")
        if source not in self.nodes:
            self.add_node(source)
        if target not in self.nodes:
            self.add_node(target)
        e = Edge(source, target, predicate)
        self.edges.append(e)
        return e

    def remove_edge(self, idx: int) -> bool:
        if 0 <= idx < len(self.edges):
            self.edges.pop(idx)
            return True
        return False

    def add_attribute(self, entity: str, name: str, value: str) -> Attribute:
        entity = (entity or "").strip()
        name = (name or "").strip()
        value = (value or "").strip()
        if not (entity and name):
            raise ValueError("entity/name не могут быть пустыми")
        if self._generic_filter(entity):
            raise ValueError(
                f"«{entity}» — служебное слово, не может быть entity атрибута")
        if entity not in self.nodes:
            self.add_node(entity)
        a = Attribute(entity, name, value)
        self.attributes.append(a)
        return a

    def remove_attribute(self, idx: int) -> bool:
        if 0 <= idx < len(self.attributes):
            self.attributes.pop(idx)
            return True
        return False

    # ------------------------------------------------------------------
    # Слияние графов (аддитивно)
    # ------------------------------------------------------------------
    def merge(self, other: "KnowledgeGraph") -> Dict[str, int]:
        """Слить другой граф в текущий.

        Политика (аддитивная, без перезаписи):
          * Узлы: добавляются только отсутствующие. Тип и props
            существующих узлов НЕ меняются — текущий граф «выигрывает».
          * Рёбра: добавляются только отсутствующие
            (дедуп по source/target/predicate).
          * Атрибуты: добавляются только отсутствующие
            (дедуп по entity/name/value).
          * Атомы, отфильтрованные generic_filter (служебные слова,
            OCR-мусор и т.п.), пропускаются и учитываются как skipped.

        Возвращает dict со статистикой:
          added_nodes, added_edges, added_attributes,
          skipped_nodes, skipped_edges, skipped_attributes.
        """
        stats = {
            "added_nodes": 0, "skipped_nodes": 0,
            "added_edges": 0, "skipped_edges": 0,
            "added_attributes": 0, "skipped_attributes": 0,
        }
        if other is None:
            return stats

        # ---- Узлы ----
        for nid, n in other.nodes.items():
            if nid in self.nodes:
                # Существующий узел не трогаем: ни тип, ни props.
                stats["skipped_nodes"] += 1
                continue
            try:
                self.add_node(nid, n.type, n.props)
                stats["added_nodes"] += 1
            except Exception:
                stats["skipped_nodes"] += 1

        # ---- Рёбра ----
        existing_edges = {(e.source, e.target, e.predicate)
                          for e in self.edges}
        for e in other.edges:
            key = (e.source, e.target, e.predicate)
            if key in existing_edges:
                stats["skipped_edges"] += 1
                continue
            try:
                self.add_edge(e.source, e.target, e.predicate)
                existing_edges.add(key)
                stats["added_edges"] += 1
            except Exception:
                stats["skipped_edges"] += 1

        # ---- Атрибуты ----
        existing_attrs = {(a.entity, a.name, a.value)
                          for a in self.attributes}
        for a in other.attributes:
            key = (a.entity, a.name, a.value)
            if key in existing_attrs:
                stats["skipped_attributes"] += 1
                continue
            try:
                self.add_attribute(a.entity, a.name, a.value)
                existing_attrs.add(key)
                stats["added_attributes"] += 1
            except Exception:
                stats["skipped_attributes"] += 1

        return stats

    def merge_from_prolog(
        self,
        text: str,
        generic_filter: Optional[Callable[[str], bool]] = None,
    ) -> Dict[str, int]:
        """Разобрать Prolog-текст и слить в текущий граф.

        Удобная обёртка над `merge(from_prolog(text))`.
        """
        other = self.__class__.from_prolog(
            text or "", generic_filter=generic_filter)
        return self.merge(other)

    # ------------------------------------------------------------------
    # Сериализация
    # ------------------------------------------------------------------
    def to_prolog(self) -> str:
        lines: List[str] = []
        for n in self.nodes.values():
            if self._generic_filter(n.id):
                continue
            props = _props_to_prolog(n.props)
            lines.append(f"node({_atom(n.id)}, {props}, {_atom(n.type)}).")
        for e in self.edges:
            if self._generic_filter(e.source) or self._generic_filter(e.target):
                continue
            lines.append(
                f"edge({_atom(e.source)}, {_atom(e.target)}, "
                f"{_atom(e.predicate)})."
            )
        for a in self.attributes:
            if self._generic_filter(a.entity):
                continue
            lines.append(
                f"attribute({_atom(a.entity)}, {_atom(a.name)}, "
                f"{_quote(a.value)})."
            )
        return "\n".join(lines) + ("\n" if lines else "")

    @classmethod
    def from_prolog(cls, text: str,
                    generic_filter: Optional[Callable[[str], bool]] = None,
                    ) -> "KnowledgeGraph":
        g = cls(generic_filter=generic_filter)
        for clause in _split_clauses(text or ""):
            _apply_clause(g, clause)
        return g

    def summary(self) -> Dict[str, int]:
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "attributes": len(self.attributes),
        }


# ======================================================================
# Вспомогательные функции
# ======================================================================
_VALID_ATOM = re.compile(r"^[a-z][A-Za-z0-9_]*$")
_RESERVED_ATOMS = {"is", "mod", "div", "rem", "xor", "not"}


def _quote(s: str) -> str:
    s = (s or "")
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _atom(s: str) -> str:
    s = (s or "").strip()
    if _VALID_ATOM.match(s) and s not in _RESERVED_ATOMS:
        return s
    return _quote(s)


def _props_to_prolog(props: Dict[str, str]) -> str:
    if not props:
        return "[]"
    items = ", ".join(f"{_atom(k)}={_quote(v)}" for k, v in props.items())
    return f"[{items}]"


def _split_clauses(text: str) -> List[str]:
    out: List[str] = []
    buf: List[str] = []
    depth = 0
    i = 0
    in_str = False
    str_ch = ""
    in_block = False
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            i += 1
            continue
        if not in_str:
            if ch == "%":
                while i < len(text) and text[i] != "\n":
                    i += 1
                continue
            if ch == "/" and nxt == "*":
                in_block = True
                i += 2
                continue
            if ch in ("'", '"'):
                in_str = True
                str_ch = ch
                buf.append(ch)
            elif ch == "(":
                depth += 1
                buf.append(ch)
            elif ch == ")":
                depth = max(0, depth - 1)
                buf.append(ch)
            elif ch == "." and depth == 0:
                s = "".join(buf).strip()
                if s:
                    out.append(s)
                buf = []
            else:
                buf.append(ch)
        else:
            buf.append(ch)
            if ch == "\\" and nxt:
                buf.append(nxt)
                i += 2
                continue
            if ch == str_ch:
                in_str = False
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


_CLAUSE_RE = re.compile(r"^([a-z][A-Za-z0-9_]*)\s*\((.*)\)$", re.S)


def _split_top(s: str, sep: str) -> List[str]:
    parts: List[str] = []
    depth = 0
    in_str = False
    str_ch = ""
    buf: List[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if not in_str:
            if ch in ("'", '"'):
                in_str = True
                str_ch = ch
                buf.append(ch)
            elif ch == "(":
                depth += 1
                buf.append(ch)
            elif ch == ")":
                depth = max(0, depth - 1)
                buf.append(ch)
            elif ch == sep and depth == 0:
                parts.append("".join(buf))
                buf = []
            else:
                buf.append(ch)
        else:
            buf.append(ch)
            if ch == "\\" and nxt:
                buf.append(nxt)
                i += 2
                continue
            if ch == str_ch:
                in_str = False
        i += 1
    if buf:
        parts.append("".join(buf))
    return parts


def _str_arg(token: str) -> str:
    t = token.strip()
    if len(t) >= 2 and t[0] == "'" and t[-1] == "'":
        inner = t[1:-1]
        return inner.replace("\\'", "'").replace("\\\\", "\\")
    if t in ("_", "[]"):
        return ""
    return t


def _parse_props(token: str) -> Dict[str, str]:
    t = token.strip()
    if not t or t in ("_", "[]"):
        return {}
    if not (t.startswith("[") and t.endswith("]")):
        return {}
    body = t[1:-1].strip()
    if not body:
        return {}
    result: Dict[str, str] = {}
    for item in _split_top(body, ","):
        item = item.strip()
        if not item:
            continue
        kv = _split_top(item, "=")
        if len(kv) != 2:
            continue
        k = kv[0].strip().strip("'\"")
        v = _str_arg(kv[1].strip())
        result[k] = v
    return result


def _apply_clause(g: KnowledgeGraph, clause: str) -> None:
    m = _CLAUSE_RE.match(clause.strip())
    if not m:
        return
    functor = m.group(1)
    inner = m.group(2).strip()
    raw_args = _split_top(inner, ",") if inner else []
    args = [_str_arg(x) for x in raw_args]
    try:
        if functor == "node":
            if len(args) == 3:
                g.add_node(args[0], args[2] or "concept",
                           _parse_props(raw_args[1]))
            elif len(args) == 2:
                g.add_node(args[0], args[1] or "concept")
            elif len(args) == 1:
                g.add_node(args[0])
        elif functor == "edge" and len(args) >= 3:
            g.add_edge(args[0], args[1], args[2])
        elif functor == "attribute" and len(args) >= 3:
            g.add_attribute(args[0], args[1], args[2])
    except Exception:
        return