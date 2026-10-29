"""tests/test_corpus_quality.py — регрессионный тест качества извлечения."""
import pytest
from pathlib import Path

from run_corpus import run_on_corpus
from corpus_metrics import PRF

_CORPUS = Path(__file__).resolve().parent / "test_corpus"


@pytest.mark.parametrize("domain,min_precision,min_recall", [
    ("essay", 0.60, 0.45),
    ("news",  0.55, 0.40),
    ("regs",  0.70, 0.50),
    ("science", 0.50, 0.35),
])
def test_domain_quality(domain, min_precision, min_recall):
    results = run_on_corpus(str(_CORPUS))
    items = results.get(domain, [])
    if not items:
        pytest.skip(f"no tests for domain {domain}")
    avg_p = sum(i["triplets"]["precision"] for i in items) / len(items)
    avg_r = sum(i["triplets"]["recall"] for i in items) / len(items)
    assert avg_p >= min_precision, f"{domain} precision {avg_p:.2f}"
    assert avg_r >= min_recall, f"{domain} recall {avg_r:.2f}"