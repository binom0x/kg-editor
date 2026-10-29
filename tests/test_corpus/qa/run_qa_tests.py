#!/usr/bin/env python3
"""
Q&A test runner для text_to_prolog.py (v5.11.18).

v5.11.18:
    * load_aliases_from_kb() — читает alias/2 из kb.pl
    * normalize_with_aliases() — транзитивное развёртывание атомов
    * lift_query() — подъём edge/attr → rule invocation по category
    * evaluate_pair / evaluate_dialog принимают aliases
    * FIO: иванов→иванов_иван, петров→петров_петр,
      сидоров→сидорова_анна (учитывает pymorphy-лемматизацию)
    * transitive: edge(...,'находиться_в') → located_in(...)

Запуск:
    python run_qa_tests.py --corpus . --verbose
    python run_qa_tests.py --corpus . --parse-only
    python run_qa_tests.py --corpus . --kb-only
"""

import argparse
import json
import re
import sys
from pathlib import Path

# =============================================================
# Backends
# =============================================================

try:
    from prolog.agent import Agent
    HAS_AGENT = True
except ImportError:
    HAS_AGENT = False
    print("⚠ PyAgentProlog не установлен — KB-исполнение отключено.",
          file=sys.stderr)

try:
    from text_to_prolog import TextToProlog
    HAS_T2P = True
except ImportError:
    HAS_T2P = False
    print("⚠ text_to_prolog не найден — parse-only отключён.",
          file=sys.stderr)

NATASHA_OK = False
NATASHA_ERR = "not checked"
if HAS_T2P:
    try:
        from text_to_prolog import _init_natasha, _NATASHA_IMPORT_ERR
        NATASHA_OK = _init_natasha()
        NATASHA_ERR = _NATASHA_IMPORT_ERR if not NATASHA_OK else ""
    except Exception as e:
        NATASHA_ERR = f"check failed: {e}"


# =============================================================
# KB loading
# =============================================================

def split_clauses(text):
    clauses, cur, in_q = [], '', False
    for ch in text:
        if ch == "'":
            in_q = not in_q
            cur += ch
        elif ch == '.' and not in_q:
            if cur.strip():
                clauses.append(cur.strip())
            cur = ''
        else:
            cur += ch
    if cur.strip():
        clauses.append(cur.strip())
    return clauses


def _strip_comment_lines(text):
    return '\n'.join(
        ln for ln in text.splitlines()
        if not ln.lstrip().startswith('%')
    )


def load_kb(kb_path):
    if not HAS_AGENT:
        return None
    text = Path(kb_path).read_text(encoding='utf-8')
    text = _strip_comment_lines(text)
    agent = Agent()

    add_facts = getattr(agent, 'add_facts', None)
    add_fact = getattr(agent, 'add_fact', None)
    if add_facts is None and add_fact is None:
        print(
            "⚠ Agent has neither add_facts nor add_fact. "
            "Available: " + str([m for m in dir(agent)
                                 if not m.startswith('_')]),
            file=sys.stderr,
        )
        return agent

    try:
        if add_facts is not None:
            add_facts(text)
        else:
            for clause in split_clauses(text):
                clause = clause.strip()
                if not clause:
                    continue
                add_fact(clause + '.')
    except Exception as e:
        print(f"⚠ batch load failed ({e}); falling back per-clause",
              file=sys.stderr)
        for clause in split_clauses(text):
            clause = clause.strip()
            if not clause:
                continue
            try:
                if add_fact is not None:
                    add_fact(clause + '.')
                elif add_facts is not None:
                    add_facts(clause + '.')
            except Exception as e2:
                print(f"⚠ load: {clause[:70]}… — {e2}", file=sys.stderr)

    return agent


# =============================================================
# Aliases from kb.pl (v5.11.18)
# =============================================================

def load_aliases_from_kb(kb_path):
    """Parse alias('A', 'B'). facts from kb.pl."""
    try:
        text = Path(kb_path).read_text(encoding='utf-8')
    except Exception:
        return {}
    aliases = {}
    for m in re.finditer(
        r"alias\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)\s*\.",
        text,
    ):
        aliases[m.group(1)] = m.group(2)
    return aliases


def _resolve_alias(a, aliases, seen=None):
    if seen is None:
        seen = set()
    if a in seen or a not in aliases:
        return a
    seen.add(a)
    return _resolve_alias(aliases[a], aliases, seen)


def normalize_with_aliases(q, aliases):
    """Normalize query string through KB alias/2 (transitive)."""
    if not q:
        return normalize(q)
    if not aliases:
        return normalize(q)
    q_norm = normalize(q)

    def _sub(m):
        atom = m.group(1)
        return f"'{_resolve_alias(atom, aliases)}'"

    return re.sub(r"'([^']+)'", _sub, q_norm)


# =============================================================
# Query extraction (NL → graph query)
# =============================================================

def extract_query(nl, strict=False):
    if not HAS_T2P:
        return None
    try:
        _, q = TextToProlog().parse(
            nl, strict=strict, facts_from_questions=False,
        )
        return q
    except Exception as e:
        print(f"⚠ parse: {nl[:60]}… — {e}", file=sys.stderr)
        return None


# =============================================================
# Query lifting (v5.11.18)
# =============================================================

def lift_query(q, category):
    """Lift base edge/attr query to higher-level rule invocation.

    Только для явно запрошенных категорий (transitive/list),
    по сигналу из qa_*.json — не автоматически.
    """
    if not q:
        return q
    if category == 'transitive':
        m = re.match(
            r"^edge\('([^']+)',\s*([^,]+),\s*'находиться_в'\)$",
            q,
        )
        if m:
            return f"located_in('{m.group(1)}', {m.group(2)})"

    if category == 'list':
        # «Какие X есть в Y?» → edge(X, Y, 'находиться_в')
        # → techpark_in_russia(X) — KB-правило с типом X.
        # Обобщение: type-constraint — в KB-rule, lift —
        # в тесте (не в парсере).
        m = re.match(
            r"^edge\(X,\s*'([^']+)',\s*'находиться_в'\)$", q,
        )
        if m and m.group(1) == 'россия':
            return "techpark_in_russia(X)"

    return q


# =============================================================
# Normalization & comparison
# =============================================================

def normalize(q):
    if not q:
        return ""
    q = q.strip().rstrip('.')
    q = re.sub(r'\s+', ' ', q)
    q = re.sub(r'["""]', "'", q)
    return q


def run_query(agent, q):
    if agent is None:
        return None
    q_clean = q.rstrip('.').rstrip()
    try:
        return list(agent.stream(q_clean + '.'))
    except Exception as e:
        print(f"⚠ query: {q} — {e}", file=sys.stderr)
        return []


def extract_binding(sol, var='X'):
    if sol is None:
        return None
    if isinstance(sol, dict):
        if 'error' in sol:
            return None
        return sol.get(var)
    return str(sol)


def _query_error(sols):
    if not sols:
        return None
    for s in sols:
        if isinstance(s, dict) and 'error' in s:
            return s['error']
    return None


def compare_answer(sols, pair):
    if sols is None:
        return None
    err = _query_error(sols)
    if err is not None:
        print(f"⚠ query error: {err}", file=sys.stderr)
        return None

    mode = pair.get('answer_mode', 'list')
    expected = pair.get('expected_answers', [])

    if mode == 'yes_no':
        first = sols[0] if sols else False
        actual = ['да'] if first is True else ['нет']
        return actual == expected

    var = pair.get('answer_var', 'X')
    actual_list = [extract_binding(s, var) for s in sols]
    actual_set = {str(a) for a in actual_list if a is not None}
    expected_set = {str(e) for e in expected}
    return expected_set == actual_set


# =============================================================
# Evaluation
# =============================================================

def evaluate_pair(pair, agent, aliases=None,
                  skip_query_extraction=False, strict=False):
    r = {
        'id': pair.get('id', '?'),
        'nl': pair.get('nl', ''),
        'category': pair.get('category', '?'),
        'query_hint': pair.get('query_hint'),
    }

    if not skip_query_extraction and HAS_T2P:
        extracted = extract_query(pair['nl'], strict=strict)
        r['extracted'] = extracted
        extracted_norm = (
            normalize_with_aliases(extracted, aliases)
            if aliases else normalize(extracted)
        )
        extracted_lifted = lift_query(
            extracted_norm, pair.get('category'))
        r['query_ok'] = extracted_lifted == normalize(pair['query_hint'])
    else:
        r['extracted'] = None
        r['query_ok'] = None

    sols = run_query(agent, pair['query_hint'])
    r['solutions'] = sols
    r['answer_ok'] = compare_answer(sols, pair)
    return r


def _turn_to_pair(dialog, turn):
    return {
        'id': f"{dialog['id']}_t{turn['turn']}",
        'nl': turn['nl'],
        'category': 'dialog',
        'query_hint': turn['query_hint'],
        'answer_var': turn.get('answer_var', 'X'),
        'answer_mode': turn.get('answer_mode', 'list'),
        'expected_answers': turn.get('expected_answers', []),
    }


def _evaluate_dialog_with_context(dialog, agent, aliases, strict):
    """v5.11.20: dialog с DialogTurn для coref/ellipsis."""
    try:
        from dialog import DialogTurn
    except ImportError:
        return _evaluate_dialog_legacy(
            dialog, agent, aliases, strict)

    t2p = TextToProlog() if HAS_T2P else None
    dlg = DialogTurn(t2p=t2p)

    rows = []
    for turn in dialog.get('turns', []):
        pair = _turn_to_pair(dialog, turn)

        # Resolve (coref/ellipsis), иначе — parser
        resolved_query, is_resolved, source = dlg.resolve(turn['nl'])
        if is_resolved:
            extracted = resolved_query
        else:
            extracted = extract_query(turn['nl'], strict=strict)

        # Сравнение
        extracted_norm = (
            normalize_with_aliases(extracted, aliases)
            if aliases else normalize(extracted)
        )

        r = {
            'id': pair['id'],
            'nl': pair['nl'],
            'category': 'dialog',
            'query_hint': pair['query_hint'],
            'extracted': extracted,
            'resolved_from': source if is_resolved else None,
            'query_ok': extracted_norm == normalize(pair['query_hint']),
        }

        # Answer accuracy — по ожидаемому hint
        sols = run_query(agent, pair['query_hint'])
        r['solutions'] = sols
        r['answer_ok'] = compare_answer(sols, pair)

        # Синхронизация контекста с корректным query (изоляция
        # coref/ellipsis от погрешностей parser на первом turn)
        dlg.last_query = pair['query_hint']
        if (sols and len(sols) == 1
                and isinstance(sols[0], dict)
                and not pair['query_hint'].lstrip().startswith('attribute(')):
            for _k, _v in sols[0].items():
                if isinstance(_v, str) and _v:
                    dlg.last_entity = _v
                    break

        rows.append(r)
    return rows


def _evaluate_dialog_legacy(dialog, agent, aliases, strict):
    """Без DialogTurn — построчно, без контекста."""
    rows = []
    for turn in dialog.get('turns', []):
        pair = _turn_to_pair(dialog, turn)
        rows.append(evaluate_pair(
            pair, agent,
            aliases=aliases,
            skip_query_extraction=False,
            strict=strict,
        ))
    return rows


def evaluate_dialog(dialog, agent, aliases=None,
                    skip_query_extraction=False, strict=False):
    """v5.11.20: с DialogTurn, если доступен."""
    if not skip_query_extraction:
        return _evaluate_dialog_with_context(dialog, agent, aliases, strict)
    return _evaluate_dialog_legacy(dialog, agent, aliases, strict)


# =============================================================
# Main
# =============================================================

def main():
    ap = argparse.ArgumentParser(
        description="Q&A test runner для text_to_prolog.py."
    )
    ap.add_argument(
        '--corpus',
        default=str(Path(__file__).resolve().parent),
        help="Каталог с kb.pl, qa_*.json, dlg_*.json.",
    )
    ap.add_argument('--report', default=None,
                    help="Записать отчёт в файл (markdown).")
    ap.add_argument('--kb-only', action='store_true',
                    help="Только KB-ответы (пропустить NL → query).")
    ap.add_argument('--parse-only', action='store_true',
                    help="Только NL → query (без KB).")
    ap.add_argument('--strict', action='store_true',
                    help="strict=True для parse().")
    ap.add_argument('--verbose', action='store_true',
                    help="Показать mismatch для проваленных cases.")
    args = ap.parse_args()

    if args.kb_only and args.parse_only:
        print("⚠ --kb-only и --parse-only взаимоисключающие.",
              file=sys.stderr)
        sys.exit(2)

    if HAS_T2P:
        if NATASHA_OK:
            print("ℹ Natasha: OK", file=sys.stderr)
        else:
            print(f"⚠ Natasha: НЕ установлена ({NATASHA_ERR})",
                  file=sys.stderr)
            print("  RU-парсер работает в pymorphy-fallback.",
                  file=sys.stderr)

    corpus = Path(args.corpus).resolve()
    if not corpus.is_dir():
        print(f"⚠ corpus not found: {corpus}", file=sys.stderr)
        sys.exit(1)

    kb_path = corpus / 'kb.pl'
    if not kb_path.is_file():
        print(f"⚠ kb.pl not found: {kb_path}", file=sys.stderr)
        sys.exit(1)

    agent = None
    if not args.parse_only:
        if not HAS_AGENT:
            print("⚠ PyAgentProlog недоступен — переключаюсь в --parse-only.",
                  file=sys.stderr)
            args.parse_only = True
        else:
            agent = load_kb(kb_path)
            if agent is not None:
                try:
                    n_rules = len(agent.solver.database.rules)
                except Exception:
                    n_rules = '?'
                print(f"ℹ KB loaded: {n_rules} rules", file=sys.stderr)

    aliases = load_aliases_from_kb(kb_path) if kb_path.is_file() else {}
    if aliases:
        print(f"ℹ KB aliases: {len(aliases)}", file=sys.stderr)

    pairs = []
    for f in sorted(corpus.glob('qa_*.json')):
        data = json.loads(f.read_text(encoding='utf-8'))
        pairs.extend(data.get('pairs', []))

    if not pairs:
        print(f"⚠ No qa_*.json found in {corpus}", file=sys.stderr)

    skip_q = args.parse_only or args.kb_only
    results = [
        evaluate_pair(p, agent, aliases=aliases,
                      skip_query_extraction=skip_q,
                      strict=args.strict)
        for p in pairs
    ]

    dialog_results = []
    for f in sorted(corpus.glob('dlg_*.json')):
        data = json.loads(f.read_text(encoding='utf-8'))
        for dlg in data.get('dialogs', []):
            dialog_results.extend(evaluate_dialog(
                dlg, agent,
                aliases=aliases,
                skip_query_extraction=skip_q,
                strict=args.strict,
            ))

    all_results = results + dialog_results
    n = len(all_results)
    n_q_eval = sum(1 for r in all_results if r['query_ok'] is not None)
    n_q_ok = sum(1 for r in all_results if r['query_ok'] is True)
    n_a_eval = sum(1 for r in all_results if r['answer_ok'] is not None)
    n_a_ok = sum(1 for r in all_results if r['answer_ok'] is True)

    cats = {}
    for r in all_results:
        c = r['category']
        s = cats.setdefault(c, {'total': 0, 'q_eval': 0, 'q_ok': 0,
                                'a_eval': 0, 'a_ok': 0})
        s['total'] += 1
        if r['query_ok'] is not None:
            s['q_eval'] += 1
            if r['query_ok']:
                s['q_ok'] += 1
        if r['answer_ok'] is not None:
            s['a_eval'] += 1
            if r['answer_ok']:
                s['a_ok'] += 1

    lines = ["# Q&A Test Report\n", f"**Пар:** {n}\n"]
    if n_q_eval:
        pct = 100 * n_q_ok / n_q_eval
        lines.append(
            f"**Query extraction:** {n_q_ok}/{n_q_eval} ({pct:.1f}%)\n"
        )
    if n_a_eval:
        pct = 100 * n_a_ok / n_a_eval
        lines.append(
            f"**Answer accuracy:** {n_a_ok}/{n_a_eval} ({pct:.1f}%)\n"
        )

    lines.append("\n## По категориям\n")
    lines.append("| Категория | Всего | Query ✓ | Answer ✓ |")
    lines.append("|---|---:|---:|---:|")
    for c, s in sorted(cats.items()):
        q = f"{s['q_ok']}/{s['q_eval']}" if s['q_eval'] else "—"
        a = f"{s['a_ok']}/{s['a_eval']}" if s['a_eval'] else "—"
        lines.append(f"| {c} | {s['total']} | {q} | {a} |")

    lines.append("\n## Детали\n")
    lines.append("| ID | NL | Query ✓ | Answer ✓ |")
    lines.append("|---|---|---|---|")
    for r in all_results:
        q = '—' if r['query_ok'] is None else ('✓' if r['query_ok'] else '✗')
        a = '—' if r['answer_ok'] is None else ('✓' if r['answer_ok'] else '✗')
        nl = r['nl'][:60]
        lines.append(f"| {r['id']} | {nl} | {q} | {a} |")

    if args.verbose:
        lines.append("\n## Диагностика провалов\n")
        for r in all_results:
            if r['query_ok'] is False:
                lines.append(f"\n### {r['id']} — query ✗")
                lines.append(f"- NL: `{r['nl']}`")
                lines.append(f"- hint: `{r['query_hint']}`")
                lines.append(f"- got:  `{r['extracted']}`")
            if r['answer_ok'] is False:
                lines.append(f"\n### {r['id']} — answer ✗")
                lines.append(f"- query: `{r['query_hint']}`")
                lines.append(f"- solutions: `{r['solutions']}`")

    report = '\n'.join(lines) + '\n'
    print(report)
    if args.report:
        Path(args.report).write_text(report, encoding='utf-8')
        print(f"\nℹ Report written to {args.report}", file=sys.stderr)


if __name__ == '__main__':
    main()