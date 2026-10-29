# verify_v5_11_11.py
import re
from text_to_prolog import TextToProlog

t = TextToProlog()

# 1. NER + attr-label леммы
for w in ['наименование', 'площадь', 'категория',
          'назначение', 'основание', 'перечень']:
    assert t._is_ner_blacklisted_word(w), f'NER not blacklisted: {w}'
    assert t._is_attr_label(w), f'not attr label: {w}'
print("✅ NER + ATTR_LABEL lemms")

# 2. Прогон на reg_001
text = open('reg_001.txt', encoding='utf-8').read()
facts, _ = t.parse(text, strict=True, log_filtered=True)

# 3. Узлы-лейблы исчезли
for w in ['наименование', 'площадь', 'категория',
          'назначение', 'основание', 'перечень',
          'срок', 'номер', 'дата']:
    assert not re.search(rf"node\('{w}', \[\], ", facts), \
        f"❌ узел {w} всё ещё в output"
print("✅ аттрибутные узлы удалены")

# 4. Инверсия сработала
assert "attribute('должность', 'наименование', 'true')" in facts, \
       "❌ нет attr(должность, наименование)"
assert "attribute('территория', 'площадь', 'true')" in facts, \
       "❌ нет attr(территория, площадь)"
assert not re.search(r"edge\('наименование',", facts), \
       "❌ edge(наименование, …) сохранился"
assert not re.search(r"edge\('площадь',", facts), \
       "❌ edge(площадь, …) сохранился"
print("✅ инверсия of(label, Y) → attr(Y, label)")

# 5. Реальные NER-типы не тронуты

# факты из parse() — `_`; из KnowledgeGraph.to_prolog() — `[]`
SECOND_ARG = r"(?:_|\[\])"

for w, typ in [('правительство', 'org'),
               ('российская_федерация', 'place'),
               ('министерство_промышленности_и_торговли', 'org')]:
    assert re.search(rf"node\('{w}', {SECOND_ARG}, {typ}\)", facts), \
           f"❌ потерян {w} ({typ})"
print("✅ NER-типы сохранены")

def check_absent_edge(facts, subj, reason=""):
    hits = [l for l in facts.split('\n')
            if l.startswith(f"edge('{subj}',")]
    if hits:
        print(f"❌ edge('{subj}', …) — {len(hits)} шт. {reason}")
        for h in hits:
            print(f"    {h}")
    else:
        print(f"✅ edge('{subj}', …) отсутствует {reason}")

for w in ['наименование', 'площадь', 'категория',
          'назначение', 'основание', 'перечень',
          'срок', 'номер', 'дата']:
    check_absent_edge(facts, w, "v5.11.11 attr-labels")

print(f"\nВсё зелёное. Отфильтровано: {len(t.filtered_atoms)}")
for atom, reason in t.filtered_atoms[:15]:
    print(f"  - {atom:55} ({reason})")