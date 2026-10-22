"""
text_to_prolog.py — Преобразование естественно-языкового текста
(русский + английский) в программу на Prolog.

Поддерживаемые режимы:
    * "condition" — обёртка в user_condition(...)   (для expert_hf)
    * "graph"     — факты графа знаний node/3, edge/3, attribute/3
    * "raw"       — только тела условий (triplet/attr/fact)
    * "definition"— definition(...) по регуляркам

Автоопределение языка: если в тексте больше кириллицы — RU, если больше
латиницы — EN. Можно задать явно параметром lang="ru"|"en".

Зависимости (все опциональны):
    * pymorphy3            — для русского (рекомендуется)
    * spacy + en_core_web_sm — для английского (рекомендуется)
    * spacy + ru_core_news_sm — для русского NER (опционально, даёт склейку
                                имён типа «Илон Маск» → илон_маск)
    * без них работает упрощённый fallback
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from prolog.terms import Term, Variable

__all__ = [
    "TextToProlog",
    "extract_conditions",
    "text_to_prolog",
    "detect_lang",
]


# ===========================================================================
# ТРАНСЛИТЕРАЦИЯ — для лексической близости RU ↔ EN
# ===========================================================================
_TRANSLIT_MAP: Dict[str, str] = {
    'а': 'a',  'б': 'b',  'в': 'v',  'г': 'g',  'д': 'd',  'е': 'e',
    'ё': 'e',  'ж': 'zh', 'з': 'z',  'и': 'i',  'й': 'y',  'к': 'k',
    'л': 'l',  'м': 'm',  'н': 'n',  'о': 'o',  'п': 'p',  'р': 'r',
    'с': 's',  'т': 't',  'у': 'u',  'ф': 'f',  'х': 'kh', 'ц': 'ts',
    'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ъ': '', 'ы': 'y',  'ь': '',
    'э': 'e',  'ю': 'yu', 'я': 'ya',
}


def _translit(text: str) -> str:
    if not text:
        return ""
    return "".join(_TRANSLIT_MAP.get(ch, ch) for ch in text.lower())


# ===========================================================================
# СТОП-СЛОВА
# ===========================================================================
_STOP_WORDS_RU: Set[str] = {
    'я', 'меня', 'мне', 'мой', 'моя', 'моё', 'мои', 'ты', 'тебя', 'тебе', 'твой',
    'он', 'она', 'оно', 'они', 'их', 'его', 'её', 'нас', 'вас', 'вы', 'мы', 'себя',
    'это', 'этот', 'эта', 'эти', 'так', 'там', 'тут', 'вот', 'еще', 'уже', 'быть',
    'есть', 'нет', 'да', 'или', 'и', 'не', 'очень', 'более', 'менее',
    'все', 'весь', 'вся', 'всё', 'всех', 'всеми', 'всего', 'всем', 'всю', 'всей',
    'у', 'в', 'на', 'с', 'к', 'по', 'из', 'за', 'от', 'до', 'без', 'для', 'об',
    'при', 'через', 'между', 'среди', 'около', 'вокруг', 'после', 'перед',
}

_STOP_WORDS_EN: Set[str] = {
    'i', 'me', 'my', 'mine', 'myself',
    'you', 'your', 'yours', 'yourself',
    'he', 'him', 'his', 'himself',
    'she', 'her', 'hers', 'herself',
    'it', 'its', 'itself',
    'we', 'us', 'our', 'ours', 'ourselves',
    'they', 'them', 'their', 'theirs', 'themselves',
    'this', 'that', 'these', 'those',
    'the', 'a', 'an',
    'and', 'or', 'but', 'if', 'then', 'else',
    'is', 'are', 'was', 'were', 'be', 'been', 'being', 'am',
    'do', 'does', 'did', 'done', 'doing',
    'have', 'has', 'had', 'having',
    'will', 'would', 'shall', 'should', 'can', 'could', 'may', 'might', 'must',
    'not', 'no', 'yes', 'so', 'than', 'as', 'at', 'by', 'for', 'from',
    'in', 'into', 'of', 'on', 'onto', 'to', 'with', 'without', 'about',
    'over', 'under', 'between', 'among', 'through', 'during', 'before', 'after',
    'here', 'there', 'where', 'when', 'why', 'how', 'what', 'which', 'who', 'whom',
    'very', 'more', 'most', 'less', 'least', 'much', 'many', 'few', 'little',
    'all', 'some', 'any', 'each', 'every', 'both', 'either', 'neither',
    'other', 'another', 'such', 'same', 'only', 'just', 'also', 'too',
    'now', 'then', 'once', 'again', 'still', 'yet', 'already',
}

_ADJ_STOP_WORDS_RU: Set[str] = {
    'что', 'который', 'которая', 'которое', 'которые', 'тот', 'та', 'то', 'те',
    'этот', 'эта', 'это', 'эти', 'весь', 'вся', 'всё', 'все',
    'сам', 'сама', 'само', 'сами', 'свой', 'своя', 'своё', 'свои',
    'такой', 'такая', 'такое', 'такие', 'один', 'одна', 'одно', 'одни',
}

_ADJ_STOP_WORDS_EN: Set[str] = {
    'this', 'that', 'these', 'those',
    'some', 'any', 'each', 'every', 'both',
    'other', 'another', 'such', 'same',
    'first', 'second', 'third',
}


# ===========================================================================
# МОДАЛЬНЫЕ ГЛАГОЛЫ
# ===========================================================================
_MODAL_VERBS_RU: Set[str] = {
    'хотеть', 'желать', 'мочь', 'собираться', 'планировать',
    'намереваться', 'нуждаться', 'требоваться', 'стараться',
    'пытаться', 'решать', 'сметь', 'успеть',
}

_MODAL_VERBS_EN: Set[str] = {
    'want', 'wish', 'would', 'could', 'should',
    'may', 'might', 'must', 'can', 'will', 'shall',
    'need', 'dare', 'ought', 'plan', 'intend',
    'try', 'attempt', 'going',
}


# ===========================================================================
# ОТРИЦАНИЕ / УТВЕРЖДЕНИЕ
# ===========================================================================
_NEGATIVE_PATTERNS = {
    'ru': (r'^нет\b', r'^не\b', r'\bне\s+верно\b', r'\bбез\b', r'\bотсутствует\b'),
    'en': (r'^no\b', r'^not\b', r"\bdon'?t\b", r"\bdoesn'?t\b", r"\bdidn'?t\b",
           r"\bisn'?t\b", r"\baren'?t\b", r'\bnever\b', r'\bwithout\b',
           r'\bnot\s+correct\b', r'\bwrong\b'),
}

_NEGATIVE_WORDS = {
    'ru': {'нет', 'no', 'false', '0', 'не верно', 'неправильно'},
    'en': {'no', 'not', 'false', '0', 'nope', 'nay', 'negative', 'wrong'},
}

_AFFIRMATIVE_WORDS = {
    'ru': {'да', 'yes', 'true', '1', 'верно', 'правильно'},
    'en': {'yes', 'yeah', 'yep', 'true', '1', 'correct', 'right',
           'affirmative', 'sure', 'ok', 'okay'},
}


# ===========================================================================
# АНГЛИЙСКИЙ — таблицы для fallback-режима (без spaCy)
# ===========================================================================
_EN_COMMON_VERBS: Set[str] = {
    'have', 'do', 'make', 'get', 'go', 'come', 'see', 'know',
    'want', 'need', 'use', 'find', 'give', 'take', 'work', 'call',
    'try', 'ask', 'feel', 'become', 'leave', 'put', 'mean', 'keep',
    'let', 'begin', 'seem', 'help', 'talk', 'turn', 'start', 'show',
    'hear', 'play', 'run', 'move', 'like', 'live', 'believe', 'hold',
    'bring', 'happen', 'write', 'provide', 'sit', 'stand', 'lose',
    'pay', 'meet', 'include', 'continue', 'set', 'learn', 'change',
    'lead', 'understand', 'watch', 'follow', 'stop', 'create', 'speak',
    'read', 'spend', 'grow', 'add', 'allow', 'release', 'develop',
    'build', 'produce', 'own', 'sell', 'buy', 'install', 'launch',
    'design', 'support', 'manage', 'control', 'operate', 'require',
    'contain', 'connect', 'apply', 'process', 'store', 'send',
    'file', 'run', 'make', 'own', 'develop', 'release', 'install',
}

_EN_VERB_SUFFIXES: Tuple[str, ...] = ('ing', 'ed', 'ize', 'ise', 'ify')

_EN_ADJ_SUFFIXES: Tuple[str, ...] = (
    'ful', 'ous', 'ive', 'able', 'ible', 'al', 'ic', 'ish', 'less', 'ary',
)


def _en_lemmatize_naive(word: str) -> str:
    """Простейшая нормализация английского слова без spaCy.

    Корректно обрабатывает:
        * -ies → -y: cities → city
        * -es  → base / base+e / base-e:
              releases → release, goes → go, boxes → box, makes → make
        * -s   → base: owns → own
        * -ing → base / base+e / base без удвоенной согласной:
              making → make, running → run
        * -ed  → base / base+e / base без удвоенной согласной:
              released → release, owned → own
    """
    w = word.lower().strip()
    if len(w) <= 3:
        return w

    # -ies → -y
    if w.endswith('ies') and len(w) > 4:
        return w[:-3] + 'y'

    # -es
    if w.endswith('es') and len(w) > 3:
        cand1 = w[:-2]                        # 'releas', 'go', 'box', 'mak'
        if cand1 + 'e' in _EN_COMMON_VERBS:
            return cand1 + 'e'                # 'release', 'make'
        if cand1 in _EN_COMMON_VERBS:
            return cand1                      # 'go'
        if len(cand1) > 2 and cand1[-1] == cand1[-2]:
            cand1 = cand1[:-1]
        return cand1                          # 'box'

    # -s
    if w.endswith('s') and not w.endswith('ss'):
        return w[:-1]                         # 'owns' → 'own'

    # -ing
    if w.endswith('ing') and len(w) > 5:
        base = w[:-3]
        if base + 'e' in _EN_COMMON_VERBS:
            return base + 'e'                 # 'making' → 'make'
        if len(base) >= 2 and base[-1] == base[-2]:
            base = base[:-1]                  # 'running' → 'run'
        return base

    # -ed
    if w.endswith('ed') and len(w) > 4:
        base = w[:-2]
        if base + 'e' in _EN_COMMON_VERBS:
            return base + 'e'                 # 'released' → 'release'
        if len(base) >= 2 and base[-1] == base[-2]:
            base = base[:-1]                  # 'stopped' → 'stop'
        return base

    return w


# ===========================================================================
# ОПРЕДЕЛЕНИЕ ЯЗЫКА
# ===========================================================================
def detect_lang(text: str) -> str:
    """Грубое определение языка: 'ru' или 'en'."""
    if not text:
        return 'ru'
    cyr = len(re.findall(r'[а-яёА-ЯЁ]', text))
    lat = len(re.findall(r'[a-zA-Z]', text))
    return 'ru' if cyr >= lat else 'en'


# ===========================================================================
# ЛЕНИВАЯ ИНИЦИАЛИЗАЦИЯ ВНЕШНИХ РЕСУРСОВ
# ===========================================================================
_PYMORPHY_ANALYZER = None
_SPACY_RU = None
_SPACY_EN = None


def _get_pymorphy():
    global _PYMORPHY_ANALYZER
    if _PYMORPHY_ANALYZER is None:
        from pymorphy3 import MorphAnalyzer
        _PYMORPHY_ANALYZER = MorphAnalyzer()
    return _PYMORPHY_ANALYZER


def _get_spacy_en():
    global _SPACY_EN
    if _SPACY_EN is False:  # уже пытались и не получилось
        return None
    if _SPACY_EN is None:
        try:
            import spacy
            _SPACY_EN = spacy.load("en_core_web_sm")
        except Exception:
            _SPACY_EN = False
            return None
    return _SPACY_EN


def _get_spacy_ru():
    """Ленивая загрузка spaCy RU (ru_core_news_sm). None, если модели нет."""
    global _SPACY_RU
    if _SPACY_RU is False:
        return None
    if _SPACY_RU is None:
        try:
            import spacy
            _SPACY_RU = spacy.load("ru_core_news_sm")
        except Exception:
            _SPACY_RU = False
            return None
    return _SPACY_RU


# ===========================================================================
# ОСНОВНОЙ КЛАСС
# ===========================================================================
class TextToProlog:
    """
    Преобразует текст пользователя (вопрос или ответ) в Prolog-программу.

    Параметры
    ---------
    use_pymorphy : bool
        Использовать pymorphy3 для русского (если доступен).
    use_spacy : bool
        Использовать spaCy (en_core_web_sm / ru_core_news_sm), если доступны.
        Для русского spaCy даёт NER: склеивает имена («Илон Маск» → илон_маск).
    default_lang : {"auto", "ru", "en"}
        Язык по умолчанию, если автодетект не сработал.
    debug : bool
        Печатать отладочные сообщения.
    """

    def __init__(
        self,
        use_pymorphy: bool = True,
        use_spacy: bool = True,
        debug: bool = False,
        default_lang: str = "auto",
    ) -> None:
        self.debug = debug
        self.default_lang = default_lang
        self.use_spacy = use_spacy

        # Русский — pymorphy
        self.use_pymorphy = use_pymorphy
        if use_pymorphy:
            try:
                self._morph_ru = _get_pymorphy()
            except Exception:
                self._morph_ru = None
                self.use_pymorphy = False
        else:
            self._morph_ru = None

        # Английский (spaCy лениво)
        self._spacy_en = None
        if use_spacy:
            self._spacy_en = _get_spacy_en()

        # Русский spaCy NER (лениво)
        self._spacy_ru = None
        if use_spacy:
            self._spacy_ru = _get_spacy_ru()

    # ==================================================================
    # Публичный API
    # ==================================================================
    def convert(
        self,
        text: str,
        mode: str = "condition",
        predicate: str = "user_condition",
        lang: Optional[str] = None,
    ) -> str:
        if mode == "definition":
            return self._convert_definition(text, predicate=predicate)

        conditions = self.extract_conditions(text, lang=lang)
        if not conditions:
            return ""

        if mode == "graph":
            return self._to_graph_program(conditions)
        if mode == "raw":
            return "\n".join(self.term_to_prolog(c) + "." for c in conditions) + "\n"
        return self.conditions_to_prolog(conditions, predicate=predicate)

    def convert_answer(
        self,
        text: str,
        question_condition: Optional[Union[str, Term]] = None,
        negated: Optional[bool] = None,
        lang: Optional[str] = None,
    ) -> str:
        if lang is None:
            lang = self._resolve_lang(text)
        if negated is None:
            negated = self.detect_negation(text, lang=lang)

        lines: List[str] = []

        if question_condition is not None:
            qc_term = (
                self._parse_term_from_string(question_condition)
                if isinstance(question_condition, str)
                else question_condition
            )
            qc_str = self.term_to_prolog(qc_term)
            lines.append(
                f"false_condition({qc_str})." if negated
                else f"true_condition({qc_str})."
            )

        if not self.is_yes_no(text, lang=lang):
            conditions = self.extract_conditions(text, lang=lang)
            existing_qc = None
            if question_condition is not None:
                existing_qc = self.term_to_prolog(
                    self._parse_term_from_string(question_condition)
                    if isinstance(question_condition, str)
                    else question_condition
                )
            for c in conditions:
                if existing_qc is not None and self.term_to_prolog(c) == existing_qc:
                    continue
                lines.append(f"user_condition({self.term_to_prolog(c)}).")

        if not lines:
            return ""
        return "\n".join(lines) + "\n"

    def extract_conditions(
        self,
        text: str,
        lang: Optional[str] = None,
    ) -> List[Term]:
        if not text or not text.strip():
            return []
        if lang is None:
            lang = self._resolve_lang(text)
        if lang == 'en':
            return self._extract_conditions_en(text)
        return self._extract_conditions_ru(text)

    def detect_negation(self, text: str, lang: Optional[str] = None) -> bool:
        if not text:
            return False
        if lang is None:
            lang = self._resolve_lang(text)
        text_lower = text.strip().lower()
        if text_lower in _NEGATIVE_WORDS[lang]:
            return True
        for pat in _NEGATIVE_PATTERNS[lang]:
            if re.search(pat, text_lower):
                return True
        return False

    def is_affirmative(self, text: str, lang: Optional[str] = None) -> bool:
        if not text:
            return False
        if lang is None:
            lang = self._resolve_lang(text)
        return text.strip().lower() in _AFFIRMATIVE_WORDS[lang]

    def is_yes_no(self, text: str, lang: Optional[str] = None) -> bool:
        if not text:
            return False
        if lang is None:
            lang = self._resolve_lang(text)
        t = text.strip().lower().rstrip('!.,;:')
        return t in _NEGATIVE_WORDS[lang] or t in _AFFIRMATIVE_WORDS[lang]

    def conditions_to_prolog(
        self,
        conditions: List[Term],
        predicate: str = "user_condition",
    ) -> str:
        if not conditions:
            return ""
        return "\n".join(
            f"{predicate}({self.term_to_prolog(c)})." for c in conditions
        ) + "\n"

    def term_to_prolog(self, term: Union[Term, str]) -> str:
        if isinstance(term, str):
            return term
        if isinstance(term, Variable):
            return term.name
        if isinstance(term, Term):
            if term.functor == '.' and len(term.arguments) == 2:
                return self._list_to_prolog_syntax(term)
            if term.arguments:
                args = ', '.join(self.term_to_prolog(a) for a in term.arguments)
                return f"{term.functor}({args})"
            return str(term.functor)
        return str(term)

    # ==================================================================
    # РУССКИЙ — NER-склейка и разбор
    # ==================================================================
    def _detect_ru_ner_spans(self, text: str) -> List[Tuple[int, int, str]]:
        """Возвращает список (start_char, end_char, atom) для именованных
        сущностей в русском тексте.

        Порядок:
            1. spaCy ru_core_news_sm, если установлен и нашёл сущности.
            2. Эвристика: последовательности слов с заглавной буквы
               («Илон Маск» → илон_маск).
        """
        nlp = self._spacy_ru if self.use_spacy else None
        if nlp is not None:
            try:
                doc = nlp(text)
                spans: List[Tuple[int, int, str]] = []
                for ent in doc.ents:
                    if ent.label_ in ('PER', 'PERSON', 'ORG', 'LOC', 'GPE',
                                       'MISC', 'FAC'):
                        atom = "_".join(ent.text.lower().split())
                        spans.append((ent.start_char, ent.end_char, atom))
                if spans:
                    return spans
            except Exception as e:
                if self.debug:
                    print(f"[TextToProlog] RU spaCy error: {e}")

        # Fallback: соседние слова с заглавной → одна сущность
        spans = []
        pattern = re.compile(r'([А-ЯЁA-Z][а-яёa-zA-Z]+(?:\s+[А-ЯЁA-Z][а-яёa-zA-Z]+)+)')
        for m in pattern.finditer(text):
            atom = "_".join(m.group(1).lower().split())
            spans.append((m.start(), m.end(), atom))
        return spans

    def _build_ru_tokens(self, text: str, words: List[str]) -> List[Dict[str, Any]]:
        """Строит список токенов с информацией о NER.

        Каждый токен — dict:
            word            : str            — исходное (lowercased) слово
            parse           : pymorphy Parse | None
            norm            : str            — атом (NER-атом или normal_form)
            is_ner          : bool           — начинает NER-span
            ner_atom        : str | None     — атом span'а (только на первом)
            is_span_tail    : bool           — продолжение NER-span
        """
        text_lower = text.lower()
        positions: List[Tuple[int, int]] = []
        pos = 0
        for w in words:
            idx = text_lower.find(w, pos)
            if idx < 0:
                idx = pos
            positions.append((idx, idx + len(w)))
            pos = idx + len(w)

        ner_spans = self._detect_ru_ner_spans(text)

        # Слово → индекс span'а
        word_to_span: Dict[int, int] = {}
        for i, (ws, we) in enumerate(positions):
            for si, (ss, se, _atom) in enumerate(ner_spans):
                if ws >= ss and we <= se:
                    word_to_span[i] = si
                    break

        # Первое слово каждого span'а
        span_first: Dict[int, int] = {}
        for i in range(len(words)):
            si = word_to_span.get(i)
            if si is not None and si not in span_first:
                span_first[si] = i

        tokens: List[Dict[str, Any]] = []
        for i, w in enumerate(words):
            try:
                parse = self._morph_ru.parse(w)[0] if w else None
            except Exception:
                parse = None
            norm = parse.normal_form if parse else w
            tok: Dict[str, Any] = {
                'word': w,
                'parse': parse,
                'norm': norm,
                'is_ner': False,
                'ner_atom': None,
                'is_span_tail': False,
            }
            si = word_to_span.get(i)
            if si is not None:
                atom = ner_spans[si][2]
                if i == span_first[si]:
                    tok['is_ner'] = True
                    tok['ner_atom'] = atom
                    tok['norm'] = atom
                else:
                    tok['is_span_tail'] = True
                    tok['norm'] = atom
            tokens.append(tok)
        return tokens

    def _extract_conditions_ru(self, text: str) -> List[Term]:
        if not self.use_pymorphy or self._morph_ru is None:
            return self._extract_fallback(text, lang='ru')

        # Включаем латиницу, чтобы подхватывать SpaceX, Apple и т.п. в RU тексте
        text_lower = text.lower()
        words = re.findall(r'[a-zA-Zа-яё]+', text_lower)
        if len(words) < 2:
            if words and words[0] not in _STOP_WORDS_RU:
                return [Term('fact', [Term(words[0])])]
            return []

        tokens = self._build_ru_tokens(text, words)

        def _is_verb(t):
            return t['parse'] is not None and t['parse'].tag.POS in ('VERB', 'INFN')

        def _is_noun(t):
            # NER-сущность — noun-like по определению (pymorphy может не знать
            # редких имён, напр. «Илон» → UNKN; is_ner=True спасает).
            if t.get('is_ner'):
                return True
            p = t['parse']
            if p is None:
                return False
            if p.tag.POS in ('NOUN', 'NPRO'):
                return True
            # латинские слова считаем noun-like (SpaceX, Apple, iPhone)
            return 'LATN' in str(p.tag).upper()

        def _is_adj(t):
            return t['parse'] is not None and t['parse'].tag.POS in ('ADJF', 'ADJS')

        def _has_nomn(t):
            # NER-сущности — proper nouns, падежная информация не нужна
            if t.get('is_ner'):
                return True
            return t['parse'] is not None and 'nomn' in t['parse'].tag

        def _find_subject(idx: int) -> Optional[int]:
            for j in range(max(0, idx - 3), idx):
                if j in used:
                    continue
                t = tokens[j]
                if t['is_span_tail']:
                    continue
                if _is_noun(t) and (_has_nomn(t) or 'LATN' in str(t['parse'].tag).upper()):
                    return j
            return None

        conditions: List[Term] = []
        used: Set[int] = set()

        # 1) Глаголы → triplet
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if not _is_verb(tok):
                i += 1
                continue

            is_modal = (
                tok['parse'].tag.POS == 'VERB'
                and tok['norm'] in _MODAL_VERBS_RU
            )

            if is_modal:
                subj_idx = _find_subject(i)
                action_idx: Optional[int] = None
                for j in range(i + 1, len(tokens)):
                    tj = tokens[j]
                    if tj['is_span_tail']:
                        continue
                    if _is_verb(tj):
                        action_idx = j
                        break
                    if _is_noun(tj) and _has_nomn(tj):
                        break
                if action_idx is not None:
                    atok = tokens[action_idx]
                    pred_norm = atok['norm']
                    obj_idx: Optional[int] = None
                    for k in range(action_idx + 1, min(len(tokens), action_idx + 5)):
                        tk = tokens[k]
                        if tk['is_span_tail']:
                            continue
                        if _is_noun(tk):
                            obj_idx = k
                            break
                    subj_norm = "я" if subj_idx is None else tokens[subj_idx]['norm']
                    if obj_idx is not None:
                        obj_norm = tokens[obj_idx]['norm']
                        conditions.append(Term('triplet', [
                            Term(pred_norm), Term(subj_norm), Term(obj_norm)]))
                        used.add(obj_idx)
                    else:
                        conditions.append(Term('triplet', [
                            Term(pred_norm), Term(subj_norm)]))
                    used.add(action_idx)
                    used.add(i)
                    if subj_idx is not None:
                        used.add(subj_idx)
                    i = action_idx + 1
                    continue
                used.add(i)
                i += 1
                continue

            # обычный глагол
            subj_idx = _find_subject(i)
            pred_norm = tok['norm']
            obj_idx = None
            for j in range(i + 1, min(len(tokens), i + 5)):
                tj = tokens[j]
                if tj['is_span_tail']:
                    continue
                if _is_noun(tj):
                    obj_idx = j
                    break
            subj_norm = "я" if subj_idx is None else tokens[subj_idx]['norm']
            if obj_idx is not None:
                obj_norm = tokens[obj_idx]['norm']
                conditions.append(Term('triplet', [
                    Term(pred_norm), Term(subj_norm), Term(obj_norm)]))
                used.add(obj_idx)
            else:
                conditions.append(Term('triplet', [
                    Term(pred_norm), Term(subj_norm)]))
            used.add(i)
            if subj_idx is not None:
                used.add(subj_idx)
            i += 1

        # 2) ADJ + NOUN → attr
        for k in range(len(tokens) - 1):
            t1, t2 = tokens[k], tokens[k + 1]
            if t1['is_span_tail'] or t2['is_span_tail']:
                continue
            if k in used or (k + 1) in used:
                continue
            if _is_noun(t1) and _is_adj(t2):
                conditions.append(Term('attr', [Term(t1['norm']), Term(t2['norm'])]))
                used.add(k); used.add(k + 1)
            elif _is_adj(t1) and _is_noun(t2):
                conditions.append(Term('attr', [Term(t2['norm']), Term(t1['norm'])]))
                used.add(k); used.add(k + 1)

        # 3) Составные существительные → fact
        for k in range(len(tokens) - 1):
            t1, t2 = tokens[k], tokens[k + 1]
            if t1['is_span_tail'] or t2['is_span_tail']:
                continue
            if k in used or (k + 1) in used:
                continue
            if (_is_noun(t1) and _has_nomn(t1)
                    and _is_noun(t2) and _has_nomn(t2)):
                conditions.append(Term('fact', [
                    Term(f"{t1['word']}_{t2['word']}")]))
                used.add(k); used.add(k + 1)

        # 4) Одиночные существительные → fact
        #    Используем _is_noun (а не прямой POS-чек): NER-сущности,
        #    у которых pymorphy вернул UNKN, тоже должны попасть сюда.
        for k, tok in enumerate(tokens):
            if k in used or tok['is_span_tail']:
                continue
            if not _is_noun(tok):
                p = tok['parse']
                # прилагательные-субстантиваты (ADJF/ADJS) тоже допускаем
                if p is None or p.tag.POS not in ('ADJF', 'ADJS'):
                    continue
            if (tok['word'] in _STOP_WORDS_RU
                    or tok['word'] in _ADJ_STOP_WORDS_RU):
                continue
            conditions.append(Term('fact', [Term(tok['norm'])]))
            used.add(k)

        return self._dedup(conditions, lang='ru')

    # ==================================================================
    # АНГЛИЙСКИЙ — извлечение условий
    # ==================================================================
    def _extract_conditions_en(self, text: str) -> List[Term]:
        nlp = self._spacy_en if self.use_spacy else None
        if nlp is not None:
            try:
                return self._extract_conditions_en_spacy(text, nlp)
            except Exception as e:
                if self.debug:
                    print(f"[TextToProlog] spaCy error: {e}")
        return self._extract_conditions_en_fallback(text)

    def _extract_conditions_en_spacy(self, text: str, nlp) -> List[Term]:
        doc = nlp(text)

        token_to_span: Dict[int, Any] = {}
        span_entities: List[Any] = []
        for ent in doc.ents:
            if ent.label_ in ('PERSON', 'ORG', 'GPE', 'LOC', 'MISC', 'PRODUCT', 'FAC'):
                span_entities.append(ent)
                for i in range(ent.start, ent.end):
                    token_to_span[i] = ent

        conditions: List[Term] = []
        used_tokens: Set[int] = set()

        def span_or_token(tok) -> str:
            if tok.i in token_to_span:
                ent = token_to_span[tok.i]
                for j in range(ent.start, ent.end):
                    used_tokens.add(j)
                return "_".join(ent.text.lower().split())   # ← fix: "elon musk" → "elon_musk"
            used_tokens.add(tok.i)
            lemma = (tok.lemma_ or tok.text).lower()
            return lemma

        for token in doc:
            if token.pos_ not in ('VERB', 'AUX'):
                continue
            lemma = (token.lemma_ or token.text).lower()
            if lemma in _MODAL_VERBS_EN or lemma in _STOP_WORDS_EN:
                continue
            if lemma in ('be', 'have', 'do') and token.pos_ == 'AUX':
                continue

            subj_tok = None
            for child in token.children:
                if child.dep_ in ('nsubj', 'nsubjpass'):
                    subj_tok = child
                    break

            obj_tok = None
            for child in token.children:
                if child.dep_ in ('dobj', 'obj', 'attr', 'oprd', 'dative'):
                    obj_tok = child
                    break
            if obj_tok is None:
                for child in token.children:
                    if child.dep_ == 'prep':
                        for pobj in child.children:
                            if pobj.dep_ == 'pobj':
                                obj_tok = pobj
                                break
                        if obj_tok is not None:
                            break

            subj = span_or_token(subj_tok) if subj_tok else "i"
            if subj in _STOP_WORDS_EN:
                subj = "i"

            if obj_tok is not None:
                obj = span_or_token(obj_tok)
                if obj in _STOP_WORDS_EN:
                    continue
                conditions.append(Term('triplet', [
                    Term(lemma), Term(subj), Term(obj)]))
            else:
                conditions.append(Term('triplet', [Term(lemma), Term(subj)]))

        for token in doc:
            if token.pos_ != 'ADJ':
                continue
            lemma = (token.lemma_ or token.text).lower()
            if lemma in _ADJ_STOP_WORDS_EN or lemma in _STOP_WORDS_EN:
                continue
            if token.dep_ == 'amod' and token.head.pos_ in ('NOUN', 'PROPN'):
                noun = span_or_token(token.head)
                if noun in _STOP_WORDS_EN:
                    continue
                conditions.append(Term('attr', [Term(noun), Term(lemma)]))
            elif token.dep_ in ('acomp', 'attr'):
                head = token.head
                subj_tok = None
                for child in head.children:
                    if child.dep_ in ('nsubj', 'nsubjpass'):
                        subj_tok = child
                        break
                if subj_tok is not None:
                    subj = span_or_token(subj_tok)
                    if subj not in _STOP_WORDS_EN:
                        conditions.append(Term('attr', [Term(subj), Term(lemma)]))

        for ent in span_entities:
            label = ent.text.lower()
            if label not in _STOP_WORDS_EN:
                conditions.append(Term('fact', [Term(label)]))

        for token in doc:
            if token.pos_ not in ('NOUN', 'PROPN'):
                continue
            if token.i in used_tokens:
                continue
            if token.i in token_to_span:
                continue
            lemma = (token.lemma_ or token.text).lower()
            if lemma in _STOP_WORDS_EN or lemma in _ADJ_STOP_WORDS_EN:
                continue
            conditions.append(Term('fact', [Term(lemma)]))

        return self._dedup(conditions, lang='en')

    def _extract_conditions_en_fallback(self, text: str) -> List[Term]:
        """Fallback без spaCy.

        Улучшено: глагол проверяется И по оригиналу, И по лемме
        (owns → own, released → release).
        """
        tokens = re.findall(r"[A-Za-z][A-Za-z'\-]*", text)
        if not tokens:
            return []

        lowered = [t.lower() for t in tokens]
        conditions: List[Term] = []
        used: Set[int] = set()

        for i, t in enumerate(lowered):
            if t in _STOP_WORDS_EN:
                continue
            lemma = _en_lemmatize_naive(t)
            is_verb = (
                t in _EN_COMMON_VERBS
                or lemma in _EN_COMMON_VERBS      # ← owns → own
                or any(t.endswith(suf) for suf in _EN_VERB_SUFFIXES)
                or t in _MODAL_VERBS_EN
            )
            if not is_verb or t in _MODAL_VERBS_EN:
                continue

            subj = None
            for j in range(i - 1, -1, -1):
                if j in used:
                    continue
                wj = lowered[j]
                if wj in _STOP_WORDS_EN:
                    continue
                if any(wj.endswith(suf) for suf in _EN_VERB_SUFFIXES):
                    continue
                subj = _en_lemmatize_naive(wj)
                used.add(j)
                break
            if subj is None:
                subj = "i"

            pred = lemma
            used.add(i)

            obj = None
            for j in range(i + 1, len(lowered)):
                if j in used:
                    continue
                wj = lowered[j]
                if wj in _STOP_WORDS_EN:
                    continue
                if any(wj.endswith(suf) for suf in _EN_VERB_SUFFIXES):
                    continue
                obj = _en_lemmatize_naive(wj)
                used.add(j)
                break

            if obj:
                conditions.append(Term('triplet', [Term(pred), Term(subj), Term(obj)]))
            else:
                conditions.append(Term('triplet', [Term(pred), Term(subj)]))

        for i, t in enumerate(lowered):
            if i in used or t in _STOP_WORDS_EN:
                continue
            if any(t.endswith(suf) for suf in _EN_VERB_SUFFIXES):
                continue
            if i + 1 < len(lowered) and (i + 1) not in used:
                nxt = lowered[i + 1]
                if any(t.endswith(suf) for suf in _EN_ADJ_SUFFIXES) and nxt not in _STOP_WORDS_EN:
                    noun = _en_lemmatize_naive(nxt)
                    adj = _en_lemmatize_naive(t)
                    conditions.append(Term('attr', [Term(noun), Term(adj)]))
                    used.add(i); used.add(i + 1)
                    continue
            conditions.append(Term('fact', [Term(_en_lemmatize_naive(t))]))
            used.add(i)

        return self._dedup(conditions, lang='en')

    # ==================================================================
    # Fallback без pymorphy
    # ==================================================================
    def _extract_fallback(self, text: str, lang: str) -> List[Term]:
        if lang == 'en':
            return self._extract_conditions_en_fallback(text)
        words = re.findall(r'[a-zA-Zа-яё]+', text.lower())
        result: List[Term] = []
        seen: Set[str] = set()
        for w in words:
            if w in _STOP_WORDS_RU or w in seen:
                continue
            seen.add(w)
            result.append(Term('fact', [Term(w)]))
        return result

    # ==================================================================
    # Определения
    # ==================================================================
    _DEFINITION_PATTERNS = (
        (re.compile(r'^(.+?)\s+(?:—|-|–)\s+(.+)$'), 1, 2),
        (re.compile(r'^(.+?)\s+(?:это|есть)\s+(.+)$'), 1, 2),
        (re.compile(r'^(.+?)\s*:\s*(.+)$'), 1, 2),
        (re.compile(r'^(.+?)\s+(?:is|are|means)\s+(.+)$', re.I), 1, 2),
        (re.compile(r'^(.+?)\s*=\s*(.+)$'), 1, 2),
        (re.compile(r'^определение\s+(.+?)\s*(?:—|-|–|:)\s*(.+)$', re.I), 1, 2),
        (re.compile(r'^термин\s+(.+?)\s*(?:—|-|–|:)\s*(.+)$', re.I), 1, 2),
        (re.compile(r'^definition\s+(.+?)\s*(?:—|-|–|:|=)\s*(.+)$', re.I), 1, 2),
        (re.compile(r'^term\s+(.+?)\s*(?:—|-|–|:|=)\s*(.+)$', re.I), 1, 2),
    )

    def _convert_definition(self, text: str, predicate: str = "definition") -> str:
        term = None
        definition = None
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            for pattern, ti, di in self._DEFINITION_PATTERNS:
                m = pattern.match(line)
                if m:
                    term = m.group(ti).strip()
                    definition = m.group(di).strip()
                    break
            if term:
                break
        if not term or not definition:
            return ""
        safe_term = self._escape_prolog_atom(term)
        safe_def = self._escape_prolog_atom(definition)
        return f"{predicate}('{safe_term}', '{safe_def}').\n"

    @staticmethod
    def _escape_prolog_atom(s: str) -> str:
        return s.replace("\\", "\\\\").replace("'", "\\'")

    # ==================================================================
    # Преобразование в граф знаний
    # ==================================================================
    def _to_graph_program(self, conditions: List[Term]) -> str:
        lines: List[str] = []
        for c in conditions:
            if c.functor == 'triplet' and len(c.arguments) == 3:
                pred = self._atom(c.arguments[0])
                subj = self._atom(c.arguments[1])
                obj = self._atom(c.arguments[2])
                lines.append(f"edge('{subj}', '{obj}', '{pred}').")
            elif c.functor == 'triplet' and len(c.arguments) == 2:
                pred = self._atom(c.arguments[0])
                subj = self._atom(c.arguments[1])
                lines.append(f"edge('{subj}', _, '{pred}').")
            elif c.functor == 'attr' and len(c.arguments) == 2:
                name = self._atom(c.arguments[0])
                value = self._atom(c.arguments[1])
                lines.append(f"attribute('{name}', '{value}', 'true').")
            elif c.functor == 'fact' and len(c.arguments) == 1:
                w = self._atom(c.arguments[0])
                lines.append(f"node('{w}', _, concept).")
        return "\n".join(lines) + "\n" if lines else ""

    @staticmethod
    def _atom(term) -> str:
        if isinstance(term, Term):
            if term.arguments:
                return str(term)
            return str(term.functor)
        return str(term)

    # ==================================================================
    # Вспомогательное
    # ==================================================================
    def _resolve_lang(self, text: str) -> str:
        if self.default_lang in ('ru', 'en'):
            return self.default_lang
        return detect_lang(text)

    def _dedup(self, conditions: List[Term], lang: str) -> List[Term]:
        seen: Set[str] = set()
        unique: List[Term] = []
        stop_words = _STOP_WORDS_EN if lang == 'en' else _STOP_WORDS_RU
        adj_stop = _ADJ_STOP_WORDS_EN if lang == 'en' else _ADJ_STOP_WORDS_RU
        for c in conditions:
            s = str(c)
            if s in seen:
                continue
            seen.add(s)
            if c.functor == 'fact' and c.arguments:
                w = str(c.arguments[0].functor)
                if w in stop_words or w in adj_stop:
                    continue
            unique.append(c)
        return unique

    def _parse_term_from_string(self, s: str) -> Term:
        s = s.strip().rstrip('.')
        if '(' not in s:
            return Term(s)
        idx = s.find('(')
        functor = s[:idx]
        args_str = s[idx + 1:-1]
        args: List[str] = []
        current: List[str] = []
        depth = 0
        for ch in args_str:
            if ch == ',' and depth == 0:
                args.append(''.join(current).strip())
                current = []
            else:
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                current.append(ch)
        if current:
            args.append(''.join(current).strip())
        term_args = [self._parse_term_from_string(a) for a in args if a]
        return Term(functor, term_args)

    def _list_to_prolog_syntax(self, list_term: Term) -> str:
        elements: List[str] = []
        current = list_term
        while (isinstance(current, Term)
               and current.functor == '.'
               and len(current.arguments) == 2):
            elements.append(self.term_to_prolog(current.arguments[0]))
            current = current.arguments[1]
        if (isinstance(current, Term)
                and current.functor == '[]' and not current.arguments):
            return '[' + ', '.join(elements) + ']'
        tail = self.term_to_prolog(current)
        return '[' + ', '.join(elements) + '|' + tail + ']'


# ===========================================================================
# УДОБНЫЕ ФУНКЦИИ
# ===========================================================================
def extract_conditions(text: str, **kwargs: Any) -> List[Term]:
    return TextToProlog(**kwargs).extract_conditions(text)


def text_to_prolog(
    text: str,
    mode: str = "condition",
    predicate: str = "user_condition",
    **kwargs: Any,
) -> str:
    return TextToProlog(**kwargs).convert(text, mode=mode, predicate=predicate)


# ===========================================================================
# ДЕМОНСТРАЦИЯ
# ===========================================================================
if __name__ == "__main__":
    t2p = TextToProlog(debug=True)

    samples = [
        ("Хочу выпустить цифровые финансовые активы", "condition"),
        ("У меня есть лицензия на брокерскую деятельность", "condition"),
        ("Смартфон новый", "condition"),
        ("Иван выпустил смартфон", "graph"),
        ("Илон Маск владеет SpaceX", "raw"),

        ("I want to install an application", "condition"),
        ("Apple released iPhone 14 in September 2022", "condition"),
        ("The smartphone is new", "condition"),
        ("Elon Musk owns SpaceX", "graph"),
        ("Apple owns iPhone", "raw"),

        ("Смартфон — это портативное устройство для связи", "definition"),
        ("Smartphone — a portable device for communication", "definition"),
    ]

    for text, mode in samples:
        print(f"\n=== [{mode}] {text!r}")
        print(t2p.convert(text, mode=mode))

    print("\n=== ANSWER (RU): 'нет' on attr(лицензия, наличие)")
    print(t2p.convert_answer(
        "нет",
        question_condition=Term('attr', [Term('лицензия'), Term('наличие')]),
    ))