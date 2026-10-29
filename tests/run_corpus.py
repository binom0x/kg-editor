"""run_corpus.py — Прогон TextToProlog по test_corpus и отчёт по метрикам.

Использование:
    python runner.py --corpus test_corpus --report report.md

Требует: text_to_prolog.py, graph_model.py, prolog/ в sys.path.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

from kg_editor.text_to_prolog import TextToProlog
from kg_editor.graph_model import KnowledgeGraph
from corpus_metrics import (
    load_annotation,
    compute_triplet_metrics,
    compute_attr_metrics,
    compute_node_type_metrics,
)

_HERE = Path(__file__).resolve().parent
_DEFAULT_CORPUS = _HERE / "test_corpus"

def extract_triplets(facts_src: str) -> List[tuple]:
    """Парсит facts_src через KnowledgeGraph, возвращает [(s, p, o)]."""
    g = KnowledgeGraph.from_prolog(facts_src or "")
    return [(e.source, e.predicate, e.target) for e in g.edges]


def extract_attributes(facts_src: str) -> List[tuple]:
    g = KnowledgeGraph.from_prolog(facts_src or "")
    return [(a.entity, a.name, a.value) for a in g.attributes]


def extract_nodes(facts_src: str) -> List[tuple]:
    g = KnowledgeGraph.from_prolog(facts_src or "")
    return [(n.id, n.type) for n in g.nodes.values()]


def run_on_corpus(corpus_dir: str, strict_fallback: bool = False) -> Dict:
    """Прогон всех *.annot.json, агрегирует метрики."""
    t2p = TextToProlog()
    if strict_fallback:
        t2p.FALLBACK_SUBJECT = None

    results: Dict[str, List[Dict]] = {
        "essay": [],
        "news": [],
        "regs": [],
        "science": [],
        "dialog": [],
    }
    corpus = Path(corpus_dir)
    for annot_file in corpus.rglob("*.annot.json"):
        ann = load_annotation(annot_file)
        domain = ann.get("domain", "unknown")
        if domain not in results:
            continue

        facts_src, query_src = t2p.parse(ann["text"])

        pred_triplets = extract_triplets(facts_src)
        pred_attrs = extract_attributes(facts_src)
        pred_nodes = extract_nodes(facts_src)

        gold = ann.get("gold", {})
        trip_m = compute_triplet_metrics(
            pred_triplets, gold.get("triplets", [])
        )
        attr_m = compute_attr_metrics(
            pred_attrs, gold.get("attributes", [])
        )
        node_m = compute_node_type_metrics(
            pred_nodes, gold.get("nodes", [])
        )

        results[domain].append({
            "id": ann["id"],
            "triplets": trip_m.as_dict(),
            "attributes": attr_m.as_dict(),
            "nodes": node_m.as_dict(),
        })

    return results


def format_report(results: Dict) -> str:
    lines: List[str] = ["# Test corpus report", ""]
    for domain, items in results.items():
        if not items:
            continue
        n = len(items)
        avg_tp = sum(i["triplets"]["precision"] for i in items) / n
        avg_tr = sum(i["triplets"]["recall"] for i in items) / n
        avg_tf = sum(i["triplets"]["f1"] for i in items) / n
        avg_ap = sum(i["attributes"]["precision"] for i in items) / n
        avg_ar = sum(i["attributes"]["recall"] for i in items) / n
        lines.append(f"## {domain} (n={n})")
        lines.append("")
        lines.append("| metric       | P     | R     | F1    |")
        lines.append("|--------------|-------|-------|-------|")
        lines.append(f"| triplets     | {avg_tp:.2f}  | {avg_tr:.2f}  | {avg_tf:.2f}  |")
        lines.append(f"| attributes   | {avg_ap:.2f}  | {avg_ar:.2f}  |")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(_DEFAULT_CORPUS))
    ap.add_argument("--report", default=str(_HERE / "report.md"))
    ap.add_argument("--strict", action="store_true",
                    help="FALLBACK_SUBJECT=None (strict mode)")
    args = ap.parse_args()

    results = run_on_corpus(args.corpus, strict_fallback=args.strict)
    report = format_report(results)
    Path(args.report).write_text(report, encoding="utf-8")
    print(f"Report written to {args.report}")