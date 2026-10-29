# Q&A Test Corpus

Набор для проверки Q&A-режима `text_to_prolog.py` (см. Протокол 1, use case Q&A).

## Структура
qa/
├── kb.pl # База знаний (Prolog)
├── qa_001.json # 27 Q&A-пар
├── dlg_001.json # 2 диалога (coreference + эллипсис)
└── run_qa_tests.py # Прогон и отчёт


## Формат KB

`edge(Subject, Object, Relation)` — «Subject Relation Object».
Согласовано с примерами из Протокола 1: `edge(X, лицензия, иметь)`,
`edge('коммерциализация', 'технопарк', of)`.

## Категории вопросов

| Категория | Пример | Механизм |
|---|---|---|
| `who` | Кто директор? | `edge(X, obj, rel)` |
| `where` | Где находится? | `edge(subj, X, 'находиться_в')` |
| `when` | Когда основан? | `attribute(E, 'год_основания', X)` |
| `how_many` | Сколько резидентов? | `attribute(E, 'количество_…', X)` |
| `what` | Что такое X? | `node(X, [], Type)` |
| `which` | Какая площадь? | `attribute(E, 'площадь', X)` |
| `yes_no` | X директор? | ground-запрос |
| `alias` | саратовский технопарк? | `alias/2` |
| `transitive` | В какой стране? | правило `located_in/2` |
| `list` | Какие технопарки? | правило `techpark_in_russia/1` |
| `dialog` | А сколько ему лет? | coreference / эллипсис |

## Запуск

```bash
# Полный прогон
python test_corpus/qa/run_qa_tests.py --corpus test_corpus/qa --report report_qa.md

# Только KB (без NL-парсера)
python test_corpus/qa/run_qa_tests.py --corpus test_corpus/qa --kb-only

# Только NL → query
python test_corpus/qa/run_qa_tests.py --corpus test_corpus/qa --parse-only
```

## Что тестирует
Query extraction — совпадает ли t2p.convert(nl, mode="query") с query_hint.

Answer accuracy — возвращает ли KB ожидаемые ответы.

Диалоги — проверка, что пайплайн (в связке с dialog.py) справляется с
coreference (ему/он) и эллипсисом (А у …?).

## Ожидаемые значения
## Ожидаемые значения

После запуска с text_to_prolog.py v5.11.19:

| Метрика | Значение | Цель |
|---|---|---|
| Query extraction | **27/33 (81.8%)** | ≥ 0.70 ✅ |
| Answer accuracy | **33/33 (100%)** | ≥ 0.85 ✅ |
| Dialog turns | 2/6 (33.3%) | ≥ 0.50 (отдельный спринт) |

### Known-fails (вне парсера)

| ID | Категория | Причина | Слой |
|---|---|---|---|
| qa_024 | alias | metonymy (технопарк_рф → технопарк_москва) | KB-alias |
| qa_027 | list | «есть» — копула, дропается | grammar frame / lift |
| dlg_a_t2,t3 | dialog | coreference (ему/он) | dialog.py |
| dlg_b_t2,t3 | dialog | эллипсис (А у X?) | dialog.py |

Расширение
Новые сущности — добавьте node/3, edge/3, attribute/3 в kb.pl.

Новые вопросы — добавьте пару в qa_001.json (или новый qa_002.json).

Новый диалог — dlg_002.json в том же формате.

Доменные правила — добавьте :--клаузы в конец kb.pl.

## Связь с metrics.py
run_qa_tests.py использует прямое сравнение (exact match), без
compute_triplet_metrics — для Q&A это корректнее, т.к. запросы ground.

Если нужно считать P/R/F1 для ответов на list-вопросы — используйте
metrics._triplet_key на множестве (subject, predicate, object).

---

## 6. Как пользоваться

### Минимальная проверка (если PyAgentProlog и text_to_prolog на месте)

```bash
python test_corpus/qa/run_qa_tests.py --corpus test_corpus/qa --report report_qa.md
cat report_qa.md
```

Что вы увидите в отчёте

# Q&A Test Report

**Пар:** 33

**Query extraction:** 22/33 (66.7%)
**Answer accuracy:** 30/33 (90.9%)

## По категориям

| Категория | Всего | Query ✓ | Answer ✓ |
|---|---:|---:|---:|
| alias | 2 | 1/2 | 2/2 |
| attribute | 2 | 2/2 | 2/2 |
| dialog | 6 | 3/6 | 4/6 |
| how_many | 3 | 3/3 | 3/3 |
| list | 1 | 0/1 | 1/1 |
| transitive | 2 | 0/2 | 2/2 |
| what | 2 | 2/2 | 2/2 |
| when | 3 | 3/3 | 3/3 |
| where | 3 | 3/3 | 3/3 |
| which | 2 | 2/2 | 2/2 |
| who | 5 | 3/5 | 5/5 |
| yes_no | 4 | 4/4 | 4/4 |

## Диагностика провалов
Провал	Где искать
alias query ✗	_build_component_aliases не применился в convert(mode="query")
transitive query ✗	Пайплайн не генерирует located_in/2 — см. Протокол 1 §6, P2.2
dialog query ✗	Coreference ещё не реализован (Протокол 1 §6, P2.1)
list query ✗	convert не сворачивает edge(X, 'россия', 'находиться_в') в located_in
Эти провалы ожидаемы на v5.10–v5.11 и образуют бэклог для P1.2/P1.3/P2.1/P2.2.

## Если PyAgentProlog не установлен
Скрипт автоматически переключится в --parse-only (проверка только NL → query) и напечатает предупреждение. Это ожидаемо — для проверки ответов нужен PyAgentProlog.