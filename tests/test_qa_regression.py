"""Регресс-тест: фиксирует метрики v5.11.20 как порог.

Запуск: pytest tests/test_qa_regression.py -v
"""
import subprocess
import sys
from pathlib import Path

import pytest

_QA_DIR = Path(__file__).resolve().parent / "test_corpus" / "qa"


def _run_qa_tests():
    """Прогон run_qa_tests.py, парсинг финального отчёта."""
    result = subprocess.run(
        [sys.executable, "run_qa_tests.py", "--corpus", "."],
        cwd=_QA_DIR,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _parse_metric(report: str, label: str) -> tuple[int, int]:
    """'Query extraction: 32/33 (97.0%)' → (32, 33)."""
    import re
    m = re.search(rf"{label}:\s*(\d+)/(\d+)", report)
    if not m:
        pytest.fail(f"Не найдено в отчёте: {label}")
    return int(m.group(1)), int(m.group(2))


@pytest.mark.slow
def test_qa_query_extraction():
    report = _run_qa_tests()
    ok, total = _parse_metric(report, "Query extraction")
    assert ok >= 32, (
        f"Query extraction regressed: {ok}/{total}. "
        f"Ожидалось ≥32 (v5.11.20 baseline)."
    )


@pytest.mark.slow
def test_qa_answer_accuracy():
    report = _run_qa_tests()
    ok, total = _parse_metric(report, "Answer accuracy")
    assert ok == total == 33, (
        f"Answer accuracy regressed: {ok}/{total}. "
        f"Ожидалось 33/33."
    )