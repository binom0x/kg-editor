"""schema.py — Dataclasses для аннотаций test_corpus."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class GoldTriplet:
    subject: str
    predicate: str
    object: str
    confidence: str = "high"  # "high"|"medium"|"low"
    source_span: str = ""
    notes: str = ""


@dataclass
class GoldAttr:
    entity: str
    key: str
    value: str
    confidence: str = "high"
    source_span: str = ""
    notes: str = ""


@dataclass
class GoldNode:
    id: str
    type: str
    confidence: str = "high"


@dataclass
class GoldQuery:
    question: str
    expected_answers: List[str] = field(default_factory=list)
    query_hint: str = ""


@dataclass
class Annotation:
    id: str
    domain: str  # "essay"|"news"|"regs"|"science"|"dialog"
    language: str
    text: str
    triplets: List[GoldTriplet] = field(default_factory=list)
    attributes: List[GoldAttr] = field(default_factory=list)
    nodes: List[GoldNode] = field(default_factory=list)
    aliases: List[Dict[str, str]] = field(default_factory=list)
    queries: List[GoldQuery] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DialogTurnGold:
    role: str  # "user"|"system"
    kind: str  # "question"|"answer"|"declarative"
    text: str
    expected_facts: List[str] = field(default_factory=list)
    expected_query: str = ""
    expected_answer: Any = None