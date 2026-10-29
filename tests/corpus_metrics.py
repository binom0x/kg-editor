"""metrics.py — Precision/Recall/F1 для triplet и attribute.

Сравнение с gold-аннотацией test_corpus/*.annot.json.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple


# ---------------------------------------------------------------------------
# Нормализация атомов
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    """Нормализация атома для сравнения.

    - пустая строка → "?"
    - снятие кавычек
    - lower
    - замена пробелов на _
    - удаление конечной пунктуации
    """
    s = (s or "").strip()
    if not s:
        return "?"
    s = s.strip("'\"")
    s = s.lower()
    s = re.sub(r"\s+", "_", s)
    s = s.rstrip(".,;:!?")
    return s


def _triplet_key(t) -> Tuple[str, str, str]:
    """Приводит триплет к кортежу (subj, pred, obj) для матчинга.

    t = (subject, predicate, object) или dict с ключами.
    """
    if isinstance(t, dict):
        return (_norm(t.get("subject", "")),
                _norm(t.get("predicate", "")),
                _norm(t.get("object", "")))
    return (_norm(t[0]), _norm(t[1]), _norm(t[2]))


# ---------------------------------------------------------------------------
# Precision / Recall / F1
# ---------------------------------------------------------------------------
@dataclass
class PRF:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    exact_matches: List[Tuple] = field(default_factory=list)
    missing: List[Tuple] = field(default_factory=list)
    extra: List[Tuple] = field(default_factory=list)

    @property
    def precision(self) -> float:
        d = self.tp + self.fp
        return self.tp / d if d else 0.0

    @property
    def recall(self) -> float:
        d = self.tp + self.fn
        return self.tp / d if d else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def as_dict(self) -> Dict[str, float]:
        return {
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
        }


def compute_triplet_metrics(
    predicted: Iterable,
    gold: Iterable,
    ignore_missing_confidence: Tuple[str, ...] = ("low",),
) -> PRF:
    """Exact-match P/R/F1 для триплетов.

    predicted: iterable of (subj, pred, obj)
    gold:      iterable of dict {subject, predicate, object, confidence}

    Triplet'ы с confidence из ignore_missing_confidence не входят в recall
    (но если предсказаны — считаются TP).
    """
    pred_set: Set[Tuple[str, str, str]] = {
        _triplet_key(t) for t in predicted
    }
    gold_set: Set[Tuple[str, str, str]] = set()
    gold_all: Set[Tuple[str, str, str]] = set()
    for g in gold:
        key = _triplet_key(g)
        gold_all.add(key)
        conf = g.get("confidence", "high") if isinstance(g, dict) else "high"
        if conf not in ignore_missing_confidence:
            gold_set.add(key)

    result = PRF()
    for key in pred_set:
        if key in gold_all:
            result.tp += 1
            result.exact_matches.append(key)
        else:
            result.fp += 1
            result.extra.append(key)
    for key in gold_set:
        if key not in pred_set:
            result.fn += 1
            result.missing.append(key)
    return result


def compute_attr_metrics(
    predicted: Iterable,
    gold: Iterable,
) -> PRF:
    """Exact-match P/R/F1 для атрибутов."""
    def _attr_key(a):
        if isinstance(a, dict):
            return (_norm(a.get("entity", "")),
                    _norm(a.get("key", "")),
                    _norm(a.get("value", "")))
        return (_norm(a[0]), _norm(a[1]), _norm(a[2]))

    pred_set = {_attr_key(a) for a in predicted}
    gold_set = {_attr_key(a) for a in gold}

    result = PRF()
    for key in pred_set:
        if key in gold_set:
            result.tp += 1
            result.exact_matches.append(key)
        else:
            result.fp += 1
            result.extra.append(key)
    for key in gold_set:
        if key not in pred_set:
            result.fn += 1
            result.missing.append(key)
    return result


def compute_node_type_metrics(
    predicted: Iterable,
    gold: Iterable,
) -> PRF:
    """Exact-match type для NER-узлов."""
    def _node_key(n):
        if isinstance(n, dict):
            return (_norm(n.get("id", "")), _norm(n.get("type", "")))
        return (_norm(n[0]), _norm(n[1]))

    pred_set = {_node_key(n) for n in predicted}
    gold_set = {_node_key(n) for n in gold}

    result = PRF()
    for key in pred_set:
        if key in gold_set:
            result.tp += 1
        else:
            result.fp += 1
            result.extra.append(key)
    for key in gold_set:
        if key not in pred_set:
            result.fn += 1
            result.missing.append(key)
    return result


# ---------------------------------------------------------------------------
# Загрузка аннотаций
# ---------------------------------------------------------------------------
def load_annotation(path: str | Path) -> Dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Пример использования
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Демо на фейковых данных
    predicted = [
        ("я", "стремиться", "цель"),
        ("иван", "построить", "дом"),
        ("я", "работать", "?"),  # FP
    ]
    gold = [
        {"subject": "я", "predicate": "стремиться", "object": "цель",
         "confidence": "high"},
        {"subject": "иван", "predicate": "построить", "object": "дом",
         "confidence": "high"},
        {"subject": "я", "predicate": "применять", "object": "знание",
         "confidence": "high"},
    ]
    m = compute_triplet_metrics(predicted, gold)
    print(m.as_dict())
    # → {"precision": 0.667, "recall": 0.667, "f1": 0.667, "tp": 2, "fp": 1, "fn": 1}