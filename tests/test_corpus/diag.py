"""diag.py — Диагностика рассогласования predicted ↔ gold."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from text_to_prolog import TextToProlog
from graph_model import KnowledgeGraph
from metrics import _triplet_key, _norm


def diag_annot(annot_path: str):
    ann = json.loads(Path(annot_path).read_text(encoding="utf-8"))
    print(f"\n{'='*70}\n{annot_path}\n{'='*70}")
    print(f"domain: {ann.get('domain')} | text_len: {len(ann.get('text',''))}")

    t = TextToProlog()
    facts, query = t.parse(ann["text"])
    print(f"\n--- PREDICTED facts (len={len(facts)}) ---")
    print(facts if facts else "(empty)")

    g = KnowledgeGraph.from_prolog(facts)
    pred_triplets = [(e.source, e.predicate, e.target) for e in g.edges]
    pred_attrs = [(a.entity, a.name, a.value) for a in g.attributes]
    pred_nodes = [(n.id, n.type) for n in g.nodes.values()]

    print(f"\n--- PREDICTED triplets ({len(pred_triplets)}) ---")
    for t_ in pred_triplets:
        print(f"  {t_}")
    print(f"\n--- PREDICTED attributes ({len(pred_attrs)}) ---")
    for a in pred_attrs:
        print(f"  {a}")
    print(f"\n--- PREDICTED nodes ({len(pred_nodes)}) ---")
    for n in pred_nodes:
        print(f"  {n}")

    gold = ann.get("gold", {})
    gold_triplets = gold.get("triplets", [])
    gold_attrs = gold.get("attributes", [])

    print(f"\n--- GOLD triplets ({len(gold_triplets)}) ---")
    for g_ in gold_triplets:
        print(f"  ({g_.get('subject')}, {g_.get('predicate')}, {g_.get('object')}) "
              f"[{g_.get('confidence','?')}]")

    # Пересечение
    pred_set = {_triplet_key(t_) for t_ in pred_triplets}
    gold_set = {_triplet_key(g_) for g_ in gold_triplets}

    print(f"\n--- TP (exact match) ---")
    for m in (pred_set & gold_set):
        print(f"  ✓ {m}")
    print(f"\n--- FN (в gold, нет в pred) ---")
    for m in (gold_set - pred_set):
        print(f"  ✗ {m}")
    print(f"\n--- FP (в pred, нет в gold) ---")
    for m in (pred_set - gold_set):
        print(f"  + {m}")

    # Attributes
    pred_a_set = {(_norm(a[0]), _norm(a[1]), _norm(a[2])) for a in pred_attrs}
    gold_a_set = {(_norm(g_.get("entity","")), _norm(g_.get("key","")), _norm(g_.get("value","")))
                  for g_ in gold_attrs}
    print(f"\n--- Attr TP ---")
    for m in (pred_a_set & gold_a_set):
        print(f"  ✓ {m}")
    print(f"--- Attr FN ---")
    for m in (gold_a_set - pred_a_set):
        print(f"  ✗ {m}")
    print(f"--- Attr FP ---")
    for m in (pred_a_set - gold_a_set):
        print(f"  + {m}")


if __name__ == "__main__":
    paths = sys.argv[1:] or list(Path("test_corpus").rglob("*.annot.json"))
    for p in paths:
        diag_annot(str(p))