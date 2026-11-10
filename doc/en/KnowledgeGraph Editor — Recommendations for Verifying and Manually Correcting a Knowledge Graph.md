# KnowledgeGraph Editor — Recommendations for Verifying and Manually Correcting a Knowledge Graph Using the "Filtered" Tab

**Purpose.** A practical guide to verifying NL import: how to read the filter log, what to do with each category of reason, how to distinguish a real parser error from "accepted loss," and how to correct the graph manually without losing data.

**Audience.** A user of the editor who is familiar with the basics of Prolog and the graph structure (`node/3`, `edge/3`, `attribute/3`).

---

## 1. Why the "🛡️ Filtered" Tab Is Needed

The NL parser (`nl2prolog`) aggressively removes noise: service words, OCR artifacts, NER false positives, Rel-adjectives. This is correct for graph cleanliness, but:

- some removals are **true noise**;
- some are **accepted loss** (OCR truncations of real words, domain redundancy);
- some are **potentially valuable facts** removed by mistake;
- some are **systemic configuration** that is better fixed via class attributes and re-import.

The "🛡️ Filtered" tab is the only way to see **what exactly** was removed and **why**. Without it, the user works "blindly": the graph was augmented, but what was lost is unknown.

---

## 2. How to Enable and Read the Log

1. Open **"📝 Import from NL"**.
2. Make sure the **"🛡️ Log filtered"** checkbox is enabled (it is enabled by default).
3. Load text manually or from a file.
4. Press **"📊 Facts"**.
5. Switch to the **"🛡️ Filtered"** tab in Column 2.

The table has two columns:

| term / atom | filter reason |
|---|---|
| `очень` | `generic_adj: очень` |
| `наименование_технопарка` | `compound_ner_blacklisted: наименование_технопарка` |
| `ст` | `noise_atom: ст` |
| `срок` | `attr_label node: срок` |
| `следующий` | `postfilter attr value noise: следующий` |

**Reason format** — always `<category>: <atom>`. The category is the keyword before the colon; group entries by it.

**Important:** the log shows only what was removed at the `_dedup`, `_postfilter_generic`, and `_postfilter_attr_labels` stages. It does not show all parser errors, incorrect roles, missed relations, or NER errors that did not lead to filtering.

---

## 3. Catalog of Reasons: What They Mean and What to Do

### 3.1. `generic_adj: <word>`

**What:** a service adjective / pronoun / preposition removed at the `_dedup` or `_postfilter_generic` stage.

**Examples:** `очень`, `этот`, `такой`, `следующий`, `настоящий`.

**What to do:**
- Usually leave as is — this is true noise.
- If the word is a real term in your domain (`общий`, `основной`, `капитальный`), add it to `ATTR_ADJ_WHITELIST`:

```python
from nl2prolog import TextToProlog
TextToProlog.ATTR_ADJ_WHITELIST |= {'общий', 'основной', 'капитальный'}
```

Then restart the import and check that the word has disappeared from the log.

### 3.2. `noise_atom: <atom>`

**What:** an OCR artifact, a too-short word (≤ 4 characters without `SHORT_PROTECTED`), a pure number, a document ID (`сд-4-3/21268`), a URL tail.

**Examples:** `ст`, `ых`, `пп`, `27`, `сд-4-3/21268`, `economicindex/.`.

**What to do:**
- Usually leave — this is noise.
- If a short word is a real term (`оки`, `мвт`, `гкал`, `нму`), add it to `SHORT_PROTECTED`:

```python
TextToProlog.SHORT_PROTECTED |= {'оки', 'мвт', 'гкал', 'нму'}
```

- An OCR fragment of a real word (`управа`, `писание`, `законодатель`, `регионал`) is **accepted loss**; do not restore it. If the correct entity (`управляющая_компания`) is not in the graph, add it manually.

### 3.3. `compound_ner_blacklisted: <atom>`

**What:** a compound atom that contains a lemma from `NER_ORG_BLACKLIST` — an abstract noun mistakenly tagged by Natasha as ORG/LOC/PER.

**Examples:** `наименование_технопарка`, `площадь_помещения`, `категория_земель`.

**What to do:**
- Usually leave — these are NER false positives.
- If the word is a real entity in your domain (`регламент`, `постановление`, `распоряжение`), remove the lemma from the blacklist:

```python
TextToProlog.NER_ORG_BLACKLIST -= {'регламент', 'постановление'}
```

Restart the import. `регламент_42` should appear with type `org`, not `concept`.

### 3.4. `attr_label node: <noun>`

**What:** a noun from `ATTR_LABEL_NOUNS` (`наименование`, `название`, `обозначение`, `площадь`, `категория`, `назначение`, `основание`, `перечень`, `срок`, `дата`, `номер`) ended up in an untyped node. It is an attribute label, not an entity.

**What to do:**
- Usually leave. `срок` should not be a node; it should be an attribute key.
- Check that the graph contains the correct form: `attribute(<entity>, 'срок', <value>)`. If not, add the attribute manually.
- If the word is a real entity in your domain (`перечень` as a document), remove it from `ATTR_LABEL_NOUNS`:

```python
TextToProlog.ATTR_LABEL_NOUNS -= {'перечень'}
```

### 3.5. `attr_label invert: <subject> → <object>`

**What:** this is **not a filter but an audit of reclassification**. The triplet `edge(<object>, <subject>, of)` is inverted into `attribute(<object>, <subject>, 'true')`.

**Example:** `edge('наименование', 'документ', of)` → `attribute('документ', 'наименование', 'true')`.

**What to do:**
- Usually nothing. This is correct reclassification.
- Check the "Attributes" tab: the attribute should exist.
- If the value `'true'` is meaningless, supplement it manually.

### 3.6. `attr_label attr-name: <noun>`

**What:** a noun from `ATTR_LABEL_NOUNS` ended up in the attribute name, for example `attribute('срок', 'выдачи', 'true')`. The parser made a mistake twice: it made `срок` an entity, then tried to filter it out.

**What to do:**
- Usually leave — this is noise.
- Check that the graph contains the correct attribute with the same value: `attribute(<correct_entity>, 'срок', <value>)`.
- If the word is a real entity, remove it from `ATTR_LABEL_NOUNS`.

### 3.7. `postfilter attr value noise: <adjective>`

**What:** a Rel-adjective in an attribute value, for example `attribute('документ', 'тип', 'следующий')`.

**What to do:**
- Usually leave — an attribute value should be concrete.
- If the adjective is a real value (`федеральный` in a specific context), you can add it to `ATTR_ADJ_WHITELIST`, but carefully: in normative legal acts this is almost always Rel-noise.

### 3.8. `postfilter triplet generic_adj: <word>`

**What:** a service adjective in a triplet argument, removed after `_dedup`. Usually a duplicate of `generic_adj`.

**What to do:** as in §3.1.

### 3.9. `postfilter attr name generic_adj: <word>`

**What:** the attribute name is a service adjective.

**What to do:** as in §3.6.

### 3.10. `postfilter generic_adj: <word>`

**What:** a `fact/1` with a service adjective removed at the `_postfilter_generic` stage.

**What to do:** as in §3.1.

---

## 4. What **Not** to Restore: Accepted Loss

If an entry falls into one of the categories below — **do not restore it**. This would pollute the graph.

### 4.1. OCR Truncations of Real Words

**Examples:** `управа`, `писание`, `законодатель`, `регионал`, `оговор`, `ответствие`, `техно`.

**Why:** domain redundancy compensates for truncations. In normative legal acts, "управляющая компания" occurs 100+ times; one truncation does not lose knowledge. If the correct entity is not in the graph, add it manually, and leave the truncation filtered out.

### 4.2. Rel-Adjectives in Normative Legal Acts

**Examples:** `федеральный`, `промышленный`, `коммунальный`, `административный`, `следующий`, `настоящий`.

**Why:** these are template phrases. If an entity is needed, it will be extracted from the full phrase (`федеральный_закон_№_1863`), not from a single adjective.

### 4.3. NER False Positives

**Examples:** `наименование`, `площадь`, `категория`, `назначение`, `основание`, `перечень`, `требование`, `подпись`, `соглашение`, `заявление`, `положение`, `сторона`, `рекомендация`.

**Why:** Natasha mistakenly tags them as ORG/LOC/PER in capitalized position. In the graph they should be attributes, not nodes.

### 4.4. Document Identifiers

**Examples:** `27`, `1863`, `сд-4-3/21268`.

**Why:** these are not entities but attribute values (`attribute('документ', 'номер', '1863')`). Check that such an attribute exists; if not, add it manually.

### 4.5. Service Adjectives

**Examples:** `очень`, `этот`, `такой`, `следующий`, `настоящий`.

**Why:** true noise.

**Rule:** if the graph **does not** contain the correct entity (`управляющая_компания`, `документ_1863`), add it manually. If it **does** — the truncation (`управа`, `наименование`) is not needed.

---

## 5. Practical Verification Workflow

### 5.1. Full Cycle (30–60 minutes per 3–5 page document)

**Step 1. Import with logging.**
1. Enable "🛡️ Log filtered".
2. Load the text.
3. Press "📊 Facts".
4. Note the counters: `+N nodes, +M edges, +K attributes`.

**Step 2. Review the log.**
1. Open "🛡️ Filtered".
2. Review all entries, group them by reason prefix.

**Step 3. Classify the entries.**

| Category | Action |
|---|---|
| Obvious noise (`очень`, `этот`, `ст`, `27`) | Ignore |
| Accepted loss (OCR truncations, Rel-adj in normative acts) | Ignore |
| Potentially valuable fact | Restore manually |
| Systemic error (many entries of one type) | Configure the class attribute and repeat the import |

**Step 4. Verify the graph.**
1. "Nodes" — check the top 20 by degree; there should be no `очень`, `наименование`, `площадь`, `срок`.
2. "Edges" — check the predicates `of`, `являться`, `иметь`; they often produce false links.
3. "Attributes" — check `attribute(<entity>, 'срок', ...)`, `attribute(<entity>, 'номер', ...)`; the entity should be a real entity.
4. "Prolog source" → "🔄 Refresh from graph" — visual control.

**Step 5. Manual correction.** See §6.

**Step 6. Re-import after configuration.**
1. "↺ Built-in" in the converter.
2. "📊 Facts" again.
3. Compare the counters and the log. The target entries should disappear, and the rest of the graph should not change.

**Step 7. Final check.**
1. "💾 Save" → `.pl`.
2. Open the `.pl` with your eyes.
3. Run 2–3 queries in the "🔎 Queries" tab.

### 5.2. Quick Check (5 minutes)

1. "📊 Facts" with logging enabled.
2. "🛡️ Filtered" — are there "obviously valuable" entries?
3. "Nodes" — is there garbage in the top 10 by degree?
4. If yes — configure the class attributes or delete manually.
5. "💾 Save".

---

## 6. Manual Correction: What and How

### 6.1. Restore a Mistakenly Removed Node

1. "Nodes" tab → `nid=оки`, `type=concept` → "➕".
2. If the term repeats — add it to `SHORT_PROTECTED` and repeat the import.

### 6.2. Restore a Mistakenly Removed Edge

1. "Edges" tab → `source`, `target`, `predicate` → "➕".
2. If source/target do not exist — they will be created as `concept`.
3. Refine the types via the "Nodes" tab → Type → "💾".

### 6.3. Fix a Node Type

1. "Nodes" tab → click the row.
2. Enter the correct type: `person`, `org`, `place`, `event`, `product`, `concept`.
3. "💾".

### 6.4. Fix an ID / Rename a Node

1. "Nodes" tab → click the row.
2. Enter the new ID.
3. "💾".

Behavior:
- the new ID does not exist — the node is renamed, edges and attributes are redirected;
- the new ID already exists — "✗ Node '…' already exists", data is not lost;
- the new ID is invalid (`очень`) — "✗ Rename error", the graph is untouched;
- compound IDs are allowed: `российская_федерация`, `тихий_океан`.

### 6.5. Delete a Garbage Node

1. "Nodes" tab → click → "🗑️".
2. All edges and attributes of the node are also deleted.

Careful: if the node has 10+ edges — you may be deleting a valuable hub.

### 6.6. Fix an Attribute

There is no "Edit attribute" button in the UI. Options:
1. Delete the incorrect attribute and add the correct one: `entity`, `name`, `value` → "➕".
2. Via "Prolog source": "🔄 Refresh from graph" → edit `attribute(...)` → "📥 Apply".

### 6.7. Add a Missing Attribute

1. "Attributes" tab → `entity=документ`, `name=срок`, `value=2022` → "➕".
2. If `документ` is not in the graph — it will be created as `concept`; refine the type.

### 6.8. Bulk Correction via Prolog Source

1. "Prolog source" → "🔄 Refresh from graph".
2. In the "✏️ Edit" accordion, edit the text.
3. "📥 Apply" — the graph will be replaced entirely.

**Careful:** "Apply" replaces the graph completely. First "💾 Save" the current `.pl`.

---

## 7. Typical Scenarios

### 7.1. "There Are 50 `generic_adj: следующий` Entries in the Log"

Diagnosis: a frequent Rel-adjective in normative legal acts. Action: nothing, this is true noise.

### 7.2. "There Are 20 `compound_ner_blacklisted: наименование_X` Entries in the Log"

Diagnosis: NER mistakenly tags `наименование_X` as ORG/LOC.
- If `X` is a real object or an attribute label — leave.
- If `X` is a real entity that needs to be visible — remove `наименование` from `NER_ORG_BLACKLIST`.

### 7.3. "In the Log: `noise_atom: 27`, `noise_atom: 1863`, `noise_atom: сд-4-3`"

Diagnosis: document identifiers. Action: nothing; check that `attribute('документ', 'номер', '1863')` exists.

### 7.4. "In the Log: `attr_label node: срок`, but the Graph Has No `attribute(..., 'срок', ...)`"

Diagnosis: the parser filtered out `срок` but did not create the attribute. Action: add the attribute manually.

### 7.5. "The Graph Has `node('следующий', [], concept)`, but There Is No Entry in the Log"

Diagnosis: `_is_generic_adj` did not recognize the word. Action:
1. Delete the node manually.
2. Add `следующий` to `noise_ru.txt` or to `GENERIC_ADJ`:

```python
TextToProlog.GENERIC_ADJ |= {'следующий', 'настоящий'}
```

### 7.6. "The Import Produced `+0 nodes, +0 edges, +0 attributes`, with 100+ Entries in the Log"

Diagnosis: either the text really contains no entities, or `strict=True` is too aggressive.
1. Review the text with your eyes.
2. Via the Python API, try `strict=False`; there is no separate switch in the UI.
3. If the entities are only service words — the text is not suitable for KB building.

### 7.7. "`attr_label invert: наименование → должность`, but `должность` Is Not What We Want"

Diagnosis: the reclassification is semantically incorrect. Action: remove `должность` from `ATTR_LABEL_NOUNS` and repeat the import.

### 7.8. "The Import Takes Tens of Seconds"

Diagnosis: this is not the log but Natasha/spaCy on long text. `log_filtered=True` adds <5% overhead. For `reg_001` (3 pages), 5–10 seconds is normal; for `reg_1863` (65 pages), 1–2 minutes is normal.

---

## 8. Graph Verification Checklist After NL Import

### 8.1. Minimal (2 minutes)

- [ ] Open "🛡️ Filtered" — are there entries that look like real terms?
- [ ] Open "Nodes" — is there garbage in the top 10 by degree?
- [ ] Open "Attributes" — are all entities real entities, not labels?
- [ ] "💾 Save".

### 8.2. Extended (15–30 minutes)

- [ ] All log entries are classified according to §3–§4.
- [ ] Valuable terms are restored manually.
- [ ] Systemic errors are fixed via class attributes.
- [ ] Node types are verified.
- [ ] Attributes `срок`, `номер`, `дата` have the correct entity.
- [ ] 2–3 queries produce a meaningful result.
- [ ] "💾 Save".

### 8.3. Full (for critical documents)

- [ ] Extended checklist.
- [ ] A pass through the entire `Prolog source` with your eyes.
- [ ] Cross-check against the source text: is every entity and relation in the graph?
- [ ] Snapshot/assertions test, if available.
- [ ] "💾 Save" + commit to git.

---

## 9. Prevention: How to Reduce Noise Before Import

1. **Clean OCR before import.** PDF post-processing reduces `noise_atom` by 30–50%.
2. **Remove boilerplate.** Headers, signatures, "УТВЕРЖДАЮ" — sources of `generic_adj` and `noise_atom`; remove them in the "📝 Open text" modal.
3. **Domain class attributes.** Configure them for your domain:

```python
from nl2prolog import TextToProlog

# Normative legal acts
TextToProlog.NER_ORG_BLACKLIST |= {'регламент', 'постановление', 'распоряжение'}
TextToProlog.ATTR_LABEL_NOUNS |= {'редакция', 'приложение'}

# Science
TextToProlog.SHORT_PROTECTED |= {'днк', 'рнк', 'атф', 'гц'}
TextToProlog.ATTR_ADJ_WHITELIST |= {'молярный', 'линейный'}

# Medicine
TextToProlog.SHORT_PROTECTED |= {'мкб', 'экг', 'мрт', 'кт'}
```

4. **One domain — one corpus.** Mixing normative acts and scientific articles produces noise from both sides.
5. **Test "on a small sample."** First 1–2 paragraphs, then the whole document.

---

## 10. Limitations of the Approach

1. **The log shows only atoms filtered at the `_dedup`, `_postfilter_generic`, and `_postfilter_attr_labels` stages.** It does not show all parser losses: incorrect roles, missed relations, NER errors without filtering, lemmatization errors, "accepted" truncations that did not make it into the log.
2. **No sentence context.** You see only the atom and the reason; the decision to restore requires the source text.
3. **The reasons are heuristic.** `generic_adj` may turn out to be a real term; `noise_atom` — an abbreviation; `compound_ner_blacklisted` — a real entity.
4. **There is no "restore" button.** Only manual addition of a node/edge/attribute or configuration of class attributes and re-import.
5. **Class attributes are changed in code/session.** There is no list editor in the UI; after a change, a restart/re-import is needed.
6. **The log does not replace snapshot/assertions/gold.** Regression needs tests, not just visual review.
7. **When the checkbox is disabled, the log is empty**, and overhead is zero.
8. **`attr_label invert` is not a loss but an audit of reclassification.** It cannot be "restored" as a node; you need to check the resulting `attribute/3`.
9. **Deduplication by `(atom, reason)`.** The log does not show how many times an atom occurred in the text.
10. **A custom `.py` extractor** supports `filtered_atoms` only optionally; without this, the tab will be empty.
11. **Not all reasons have a separate category.** Focus on the keyword before `:`.
12. **The UI does not allow editing an attribute** — only deleting and adding; bulk edits — via `Prolog source` with a preliminary `.pl` save.

**Main rule:** if the graph does not contain the correct entity — add it manually. If it does — there is no need to restore a truncation or a service word from the log.