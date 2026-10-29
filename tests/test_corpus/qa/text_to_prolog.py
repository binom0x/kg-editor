"""
text_to_prolog.py — Преобразование естественно-языкового текста
(русский + английский) в программу на Prolog.

Режимы: "condition"|"graph"|"raw"|"definition"|"query".
Высокоуровневый API: parse(text) -> (facts_str, query_str).

RU (v5.11.19) с forward-loop.

RU (v5.11.17) — wh-handler: убран ранний return при role is None:
    * Раньше: `if role is None: result.append(term); continue` —
      когда natasha размечает «кто» не как root/nsubj, wh-handler
      возвращал triplet(..., 'кто', ...) без замены на X. qa_01, qa_02,
      dlg_a_t1 давали `edge('кто', ...)` вместо `edge(X, ...)`.
    * Теперь: position-first проверка (`_name(subj) == wh_lemma`)
      выполняется безусловно, role используется только для
      predicate/object_adverbial fallback.

RU (v5.11.16) — role-triple для wh-subject:
    * _dedup: wh-слова в triplet НЕ generic (`кто` → NPRO).
    * Block 3: role-triple разрешён для wh-субъекта, attr/3 cleanup.

RU (v5.11.15) — wh-handler по позиции + новые грамм. фреймы:
    * _subj_of: wh-pronoun root — semantic subject.
    * Block 3: parent-fallback для nmod/appos + wh-pronoun parent.
    * wh-locative: убран guard по -ся.
    * «Есть ли X у Y?» → edge(Y, X, 'иметь').
    * Rel-adj + NOUN → compound (топоним-derived).

RU (v5.11.14) — Q&A грамматические фреймы, bugfix + UD-фолбэки.
RU (v5.11.13) — Q&A грамматические фреймы (без hardcode).
RU (v5.11.11) — attr-label nouns как атрибуты, а не узлы.
RU (v5.11.10) — факты из вопросов + корректные wh-запросы.
RU (v5.11.9)  — log_filtered (аудит фильтрации).
RU (v5.11.7)  — фильтрация коротких фрагментов и UNKN attr-value.
RU (v5.11.6)  — фильтрация unknown-фрагментов.
RU (v5.11.5)  — лемматизация как основа фильтрации.
RU (v5.11.4)  — ATTR_ADJ_WHITELIST, _load_noise_words, relational filter.
RU (v5.11.3)  — _compound_org_blacklisted без POS для компонентов.
RU (v5.11.2)  — fix A–E.
RU (v5.11.1)  — at_sentence_start.
RU (v5.11)    — POS-фильтрация через noise.
RU (v5.10.6)  — _postfilter_generic.
RU (v5.10.3)  — _dedup triplet + generic-ADJ.
RU (v5.10.2)  — _is_relative_pronoun по лемме.
"""

from __future__ import annotations

import re
import warnings
from typing import Any, Dict, List, Optional, Set, Tuple, Union

warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API",
    category=UserWarning,
)

from prolog.terms import Term, Variable

try:
    try:
        from .noise import (  # type: ignore
            is_service_word, is_common_noun_ner,
        )
    except ImportError:
        from noise import (  # type: ignore
            is_service_word, is_common_noun_ner,
        )
    _NOISE_OK = True
except Exception:
    _NOISE_OK = False

    def is_service_word(w: str, lang: str = 'ru') -> bool:
        return False

    def is_common_noun_ner(surface: str, lang: str = 'ru',
                           at_sentence_start: bool = False,
                           next_is_capitalized=None) -> bool:
        return False

__all__ = [
    "TextToProlog", "extract_conditions", "text_to_prolog",
    "parse_text", "detect_lang",
]


# ===========================================================================
# ТРАНСЛИТЕРАЦИЯ
# ===========================================================================
_TRANSLIT_MAP: Dict[str, str] = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e',
    'ё': 'e', 'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k',
    'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
    'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts',
    'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ъ': '', 'ы': 'y', 'ь': '',
    'э': 'e', 'ю': 'yu', 'я': 'ya',
}


def _translit(text: str) -> str:
    if not text:
        return ""
    return "".join(_TRANSLIT_MAP.get(ch, ch) for ch in text.lower())


def _clean_tok(s: str) -> str:
    if not s:
        return ""
    return s.strip('.,;:!?\'"«»()-–—/\\[]{}<>').lower()


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
    'что', 'чему', 'чем', 'кто', 'кого', 'кому', 'кем',
}

_STOP_WORDS_EN: Set[str] = {
    'i', 'me', 'my', 'mine', 'myself', 'you', 'your', 'yours', 'yourself',
    'he', 'him', 'his', 'himself', 'she', 'her', 'hers', 'herself',
    'it', 'its', 'itself', 'we', 'us', 'our', 'ours', 'ourselves',
    'they', 'them', 'their', 'theirs', 'themselves',
    'this', 'that', 'these', 'those', 'the', 'a', 'an',
    'and', 'or', 'but', 'if', 'then', 'else',
    'is', 'are', 'was', 'were', 'be', 'been', 'being', 'am',
    'do', 'does', 'did', 'done', 'doing', 'have', 'has', 'had', 'having',
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
    'this', 'that', 'these', 'those', 'some', 'any', 'each', 'every', 'both',
    'other', 'another', 'such', 'same', 'first', 'second', 'third',
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
    'want', 'wish', 'would', 'could', 'should', 'may', 'might', 'must',
    'can', 'will', 'shall', 'need', 'dare', 'ought', 'plan', 'intend',
    'try', 'attempt', 'going',
}


# ===========================================================================
# ВОПРОСИТЕЛЬНЫЕ СЛОВА
# ===========================================================================
_WH_LEMMAS_RU: Set[str] = {
    'кто', 'что', 'кого', 'кому', 'кем', 'ком', 'чему', 'чем',
    'чей', 'чья', 'чьё', 'чьи', 'чьего', 'чьей', 'чьих',
    'где', 'когда', 'куда', 'откуда', 'почему', 'зачем', 'как',
    'какой', 'какая', 'какое', 'какие', 'какого', 'каком', 'какую',
    'сколько',
}

_WH_WORDS_EN: Set[str] = {
    'who', 'whom', 'whose', 'what', 'which',
    'when', 'where', 'why', 'how',
}

_WH_ATTR_LEMMAS: Set[str] = {
    'какой', 'какая', 'какое', 'какие',
}


# ===========================================================================
# ОТНОСИТЕЛЬНЫЕ МЕСТОИМЕНИЯ
# ===========================================================================
_RELATIVE_PRONOUN_LEMMAS: Set[str] = {
    'который', 'которая', 'которое', 'которые', 'которых',
    'которого', 'которому', 'которой', 'которым', 'которыми',
    'котором', 'чей', 'чья', 'чьё', 'чьи',
    'чьего', 'чьему', 'чьей', 'чьим', 'чьими', 'чьём',
}


# ===========================================================================
# РЕЛЯЦИОННЫЕ СУЩЕСТВИТЕЛЬНЫЕ
# ===========================================================================
_RELATIONAL_NOUNS: Set[str] = {
    'основание', 'результат', 'помощь', 'случай', 'цель', 'условие',
}

_GENITIVE_PRED: str = 'of'


# ===========================================================================
# ПРЕДЛОГИ
# ===========================================================================
_OBJECT_PREPS: Set[str] = {
    'в', 'во', 'на', 'о', 'об', 'про', 'по', 'к', 'ко', 'за', 'под',
}

_ADVERBIAL_PREPS: Set[str] = {
    'с', 'со', 'из', 'от', 'до', 'при', 'над', 'без', 'для', 'через',
    'между', 'среди', 'около', 'вокруг', 'после', 'перед', 'сквозь',
}

_TEMPORAL_PLACE_LEMMAS: Set[str] = {
    'год', 'класс', 'будущее', 'время', 'момент', 'период',
    'век', 'месяц', 'день', 'неделя', 'час', 'минута',
    'начало', 'конец', 'середина', 'утро', 'вечер', 'ночь',
}

_SKIP_LEFTOVER_NOUNS: Set[str] = {
    'рамка', 'контекст', 'плоскость', 'сфера', 'область',
}


# ===========================================================================
# СОЦИАТИВНЫЕ ГОЛОВЫ
# ===========================================================================
_SOCIATIVE_HEADS: Set[str] = {
    'работать', 'сотрудничать', 'общаться', 'разговаривать',
    'встречаться', 'знакомиться', 'познакомиться', 'играть',
    'бороться', 'сражаться', 'справиться', 'видеться', 'созваниваться',
    'работа', 'сотрудничество', 'связь', 'контакт', 'знакомство',
    'общение', 'диалог', 'встреча', 'переговоры', 'договор',
    'игра', 'разговор',
}


# ===========================================================================
# OCR-АРТЕФАКТЫ
# ===========================================================================
_OCR_ARTIFACTS: Set[str] = {
    'ых', 'ов', 'га', 'кв', 'м', 'г', 'н', 'д', 'х', '_', '%',
    '4_х', '5_х', 'электро', 'тепло', 'газо', 'научно',
    'купли', 'оъект',
    'ф', 'п', 'о', 'др',
    'ст', 'пп', 'см', 'ред', 'сокр',
}


# ===========================================================================
# SHORT_PROTECTED
# ===========================================================================
_SHORT_PROTECTED: Set[str] = {
    'нко', 'ип', 'рф', 'ндс', 'фнс', 'егрн', 'фда', 'гисп', 'кдес', 'мвт',
    'млн', 'тыс', 'руб', 'сут', 'куб',
    'акт', 'вид', 'код', 'тип', 'цель', 'мера', 'срок',
    'труд', 'груз', 'сеть', 'мост', 'порт', 'суд',
    'банк', 'сбор', 'снос', 'зал', 'год', 'фонд',
}


# ===========================================================================
# TEMPLATE LEAK & DOCUMENT IDs
# ===========================================================================
_TEMPLATE_LEAK_RE = re.compile(
    r'«\s*_*\s*»'
    r'|^\s*[_/\-]+\s*$'
    r'|_/_'
    r'|[<>{}]\s*_'
    r'|\(\s*(?:наименование|дата|номер|Ф\.И\.О\.|ф\.и\.о\.)',
    re.UNICODE,
)

_DOC_ID_RE = re.compile(
    r'^[А-ЯЁA-Z]{0,4}-?\d+(?:[-\d/]*\d)?@?$',
    re.UNICODE | re.IGNORECASE,
)


def _is_pure_number(s: str) -> bool:
    if not s:
        return False
    clean = _clean_tok(s)
    if not clean:
        return False
    return bool(re.fullmatch(r'\d+[\.,]?\d*|\d+-\d+', clean))


# ===========================================================================
# NER ORG BLACKLIST — ЛЕММЫ
# ===========================================================================
_NER_ORG_BLACKLIST: Set[str] = {
    'требование', 'подпись', 'соглашение', 'заявление',
    'положение', 'сторона', 'рекомендация',
    'объём', 'объем',
    'ип', 'нко',
    'наименование', 'площадь', 'категория',
    'назначение', 'основание', 'перечень',
}


# ===========================================================================
# GENERIC_ADJ
# ===========================================================================
_GENERIC_ADJ: Set[str] = {
    'агро', 'градо',
}


# ===========================================================================
# NER → ГРАФОВЫЕ ТИПЫ
# ===========================================================================
_NER_TO_GRAPH_TYPE: Dict[str, str] = {
    'PER': 'person', 'PERSON': 'person',
    'LOC': 'place', 'GPE': 'place', 'FAC': 'place',
    'ORG': 'org',
    'PRODUCT': 'product',
    'EVENT': 'event',
    'WORK_OF_ART': 'thing',
    'MISC': 'concept',
    'NORP': 'concept',
}


# ===========================================================================
# ОТРИЦАНИЕ / УТВЕРЖДЕНИЕ
# ===========================================================================
_NEGATIVE_PATTERNS = {
    'ru': (
        r'^нет\b', r'\bне\b', r'\bне\s+верно\b', r'\bнеправильно\b',
        r'\bбез\b', r'\bотсутствует\b', r'\bникогда\b', r'\bнигде\b', r'\bничего\b',
    ),
    'en': (
        r'^no\b', r'^not\b', r"\bdon'?t\b", r"\bdoesn'?t\b", r"\bdidn'?t\b",
        r"\bisn'?t\b", r"\baren'?t\b", r"\bwon'?t\b", r"\bcan'?t\b",
        r'\bcannot\b', r'\bnever\b', r'\bwithout\b',
        r'\bnot\s+correct\b', r'\bwrong\b',
    ),
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
# EN — fallback-таблицы
# ===========================================================================
_EN_COMMON_VERBS: Set[str] = {
    'have', 'do', 'make', 'get', 'go', 'come', 'see', 'know', 'want', 'need',
    'use', 'find', 'give', 'take', 'work', 'call', 'try', 'ask', 'feel',
    'become', 'leave', 'put', 'mean', 'keep', 'let', 'begin', 'seem', 'help',
    'talk', 'turn', 'start', 'show', 'hear', 'play', 'run', 'move', 'like',
    'live', 'believe', 'hold', 'bring', 'happen', 'write', 'provide', 'sit',
    'stand', 'lose', 'pay', 'meet', 'include', 'continue', 'set', 'learn',
    'change', 'lead', 'understand', 'watch', 'follow', 'stop', 'create',
    'speak', 'read', 'spend', 'grow', 'add', 'allow', 'release', 'develop',
    'build', 'produce', 'own', 'sell', 'buy', 'install', 'launch', 'design',
    'support', 'manage', 'control', 'operate', 'require', 'contain', 'connect',
    'apply', 'process', 'store', 'send', 'file',
    'acquire', 'admire', 'announce', 'approve', 'arrive', 'compare', 'complete',
    'compete', 'compose', 'declare', 'decide', 'define', 'delete', 'describe',
    'desire', 'divide', 'escape', 'examine', 'exercise', 'expire', 'explain',
    'explore', 'express', 'fire', 'generate', 'hire', 'hope', 'imagine',
    'improve', 'inspire', 'introduce', 'invite', 'involve', 'judge', 'love',
    'measure', 'notice', 'observe', 'offer', 'organize', 'prepare', 'promise',
    'propose', 'quote', 'raise', 'rate', 'receive', 'recognize', 'reduce',
    'refer', 'refuse', 'relate', 'remain', 'remember', 'remove', 'replace',
    'resolve', 'respond', 'retire', 'return', 'review', 'rise', 'save',
    'serve', 'settle', 'share', 'smile', 'solve', 'survive', 'taste', 'trade',
    'travel', 'treat', 'trust', 'update', 'vote', 'wave',
    'found', 'accept', 'affect', 'collect', 'conduct', 'construct', 'detect',
    'expect', 'inject', 'inspect', 'instruct', 'protect', 'reflect', 'reject',
    'respect', 'select',
}

_EN_VERB_SUFFIXES: Tuple[str, ...] = ('ing', 'ed', 'ize', 'ise', 'ify')
_EN_ADJ_SUFFIXES: Tuple[str, ...] = (
    'ful', 'ous', 'ive', 'able', 'ible', 'al', 'ic', 'ish', 'less', 'ary',
)
_EN_IS_FORMS: Set[str] = {'is', 'are', 'was', 'were', 'be', 'been', 'am'}


def _en_lemmatize_naive(word: str) -> str:
    w = word.lower().strip()
    if len(w) <= 3:
        return w
    if w.endswith('ies') and len(w) > 4:
        return w[:-3] + 'y'
    if w.endswith('es') and len(w) > 3:
        cand1 = w[:-2]
        if cand1 + 'e' in _EN_COMMON_VERBS:
            return cand1 + 'e'
        if cand1 in _EN_COMMON_VERBS:
            return cand1
        if len(cand1) > 2 and cand1[-1] == cand1[-2]:
            cand1 = cand1[:-1]
        return cand1
    if w.endswith('s') and not w.endswith('ss'):
        return w[:-1]
    if w.endswith('ing') and len(w) > 5:
        base = w[:-3]
        if base + 'e' in _EN_COMMON_VERBS:
            return base + 'e'
        if len(base) >= 2 and base[-1] == base[-2]:
            base = base[:-1]
        return base
    if w.endswith('ed') and len(w) > 4:
        base = w[:-2]
        if base + 'e' in _EN_COMMON_VERBS:
            return base + 'e'
        if base in _EN_COMMON_VERBS:
            return base
        if len(base) >= 2 and base[-1] == base[-2]:
            base = base[:-1]
        return base
    return w


def detect_lang(text: str) -> str:
    if not text:
        return 'ru'
    cyr = len(re.findall(r'[а-яёА-ЯЁ]', text))
    lat = len(re.findall(r'[a-zA-Z]', text))
    return 'ru' if cyr >= lat else 'en'


# ===========================================================================
# ЛЕНИВАЯ ИНИЦИАЛИЗАЦИЯ
# ===========================================================================
_PYMORPHY_ANALYZER = None
_SPACY_RU = None
_SPACY_EN = None

_NATASHA_OK = False
_NATASHA_SEGMENTER = None
_NATASHA_MORPH_VOCAB = None
_NATASHA_EMB = None
_NATASHA_MORPH_TAGGER = None
_NATASHA_SYNTAX_PARSER = None
_NATASHA_NER_TAGGER = None
_NATASHA_IMPORT_ERR = ""


def _init_natasha() -> bool:
    global _NATASHA_OK, _NATASHA_SEGMENTER, _NATASHA_MORPH_VOCAB
    global _NATASHA_EMB, _NATASHA_MORPH_TAGGER, _NATASHA_SYNTAX_PARSER
    global _NATASHA_NER_TAGGER, _NATASHA_IMPORT_ERR
    if _NATASHA_OK:
        return True
    if _NATASHA_IMPORT_ERR:
        return False
    try:
        from natasha import (
            Segmenter, MorphVocab, NewsEmbedding,
            NewsMorphTagger, NewsSyntaxParser, NewsNERTagger,
        )
        _NATASHA_SEGMENTER = Segmenter()
        _NATASHA_MORPH_VOCAB = MorphVocab()
        _NATASHA_EMB = NewsEmbedding()
        _NATASHA_MORPH_TAGGER = NewsMorphTagger(_NATASHA_EMB)
        _NATASHA_SYNTAX_PARSER = NewsSyntaxParser(_NATASHA_EMB)
        _NATASHA_NER_TAGGER = NewsNERTagger(_NATASHA_EMB)
        _NATASHA_OK = True
        return True
    except Exception as e:
        _NATASHA_IMPORT_ERR = str(e)
        return False


def _get_pymorphy():
    global _PYMORPHY_ANALYZER
    if _PYMORPHY_ANALYZER is None:
        from pymorphy3 import MorphAnalyzer
        _PYMORPHY_ANALYZER = MorphAnalyzer()
    return _PYMORPHY_ANALYZER


def _get_spacy_en():
    global _SPACY_EN
    if _SPACY_EN is False:
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
    """Преобразует текст в Prolog: parse(text, strict=False) -> (facts, query)."""

    SKIP_LEFTOVER_NOUNS: Set[str] = set(_SKIP_LEFTOVER_NOUNS)
    TEMPORAL_PLACE_LEMMAS: Set[str] = set(_TEMPORAL_PLACE_LEMMAS)
    SOCIATIVE_HEADS: Set[str] = set(_SOCIATIVE_HEADS)
    OCR_ARTIFACTS: Set[str] = set(_OCR_ARTIFACTS)
    SHORT_PROTECTED: Set[str] = set(_SHORT_PROTECTED)
    NER_ORG_BLACKLIST: Set[str] = set(_NER_ORG_BLACKLIST)
    GENERIC_ADJ: Set[str] = set(_GENERIC_ADJ)

    ATTR_LABEL_NOUNS: Set[str] = {
        'наименование', 'название', 'обозначение',
        'площадь',
        'категория', 'назначение',
        'основание',
        'перечень',
        'срок', 'дата', 'номер',
    }

    ATTR_ADJ_WHITELIST: Set[str] = {
        'полезный', 'линейный',
        'общий', 'основной', 'основный',
    }

    FALLBACK_SUBJECT: Optional[str] = "я"

    def __init__(
        self,
        use_pymorphy: bool = True,
        use_spacy: bool = True,
        use_natasha: bool = True,
        debug: bool = False,
        default_lang: str = "auto",
    ) -> None:
        self.debug = debug
        self.default_lang = default_lang
        self.use_spacy = use_spacy
        self.use_natasha = use_natasha and _init_natasha()

        self.use_pymorphy = use_pymorphy
        if use_pymorphy:
            try:
                self._morph_ru = _get_pymorphy()
            except Exception:
                self._morph_ru = None
                self.use_pymorphy = False
        else:
            self._morph_ru = None

        self._spacy_en = _get_spacy_en() if use_spacy else None
        self._spacy_ru = _get_spacy_ru() if use_spacy else None

        self._noise_words_cache: Dict[str, Set[str]] = {}

        self.filtered_atoms: List[Tuple[str, str]] = []
        self._filtered_set: Set[Tuple[str, str]] = set()
        self._log_filtered_enabled: bool = False

    def _term_key(self, c) -> str:
        if isinstance(c, Variable):
            return f"VAR:{c.name}"
        if not isinstance(c, Term):
            return f"RAW:{c}"
        args: List[str] = []
        for a in c.arguments:
            if isinstance(a, Variable):
                args.append(f"VAR:{a.name}")
            elif isinstance(a, Term):
                args.append(self._term_key(a))
            else:
                args.append(f"RAW:{a}")
        return f"{c.functor}({','.join(args)})"

    @staticmethod
    def _atom(term) -> str:
        if isinstance(term, Term):
            if term.arguments:
                return str(term)
            return str(term.functor)
        if isinstance(term, Variable):
            return term.name
        return str(term)

    # ==================================================================
    # log_filtered
    # ==================================================================
    def _log_filtered(self, atom: str, reason: str) -> None:
        if not self._log_filtered_enabled:
            return
        key = (str(atom), str(reason))
        if key in self._filtered_set:
            return
        self._filtered_set.add(key)
        self.filtered_atoms.append(key)

    def _term_desc(self, c: Term) -> str:
        if c.functor == 'fact' and c.arguments:
            return f"node({self._atom(c.arguments[0])})"
        if c.functor == 'attr' and len(c.arguments) == 2:
            return (f"attr({self._atom(c.arguments[0])}, "
                    f"{self._atom(c.arguments[1])})")
        if c.functor == 'triplet' and len(c.arguments) == 3:
            return (f"{self._atom(c.arguments[1])} "
                    f"—[{self._atom(c.arguments[0])}]→ "
                    f"{self._atom(c.arguments[2])}")
        if c.functor == 'triplet' and len(c.arguments) == 2:
            return (f"{self._atom(c.arguments[1])} "
                    f"—[{self._atom(c.arguments[0])}]→ _")
        return self.term_to_prolog(c)

    # ==================================================================
    # Лемматизация и продуктивные морфо-модели
    # ==================================================================
    def _lemmatize_noun(self, w: str) -> str:
        if not w or '_' in w:
            return w
        if not (self.use_pymorphy and self._morph_ru is not None):
            return w
        try:
            for p in self._morph_ru.parse(w):
                if p.tag.POS != 'NOUN':
                    continue
                if hasattr(p, 'is_known') and not p.is_known:
                    continue
                nf = p.normal_form
                if nf:
                    return nf
        except Exception:
            pass
        return w

    def _lemma_word(self, w: str) -> str:
        if not w:
            return ''
        wl = w.lower().strip()
        if not (self.use_pymorphy and self._morph_ru is not None):
            return wl
        try:
            p = self._morph_ru.parse(wl)
            if p and p[0].normal_form:
                return p[0].normal_form
        except Exception:
            pass
        return wl

    def _phrase_to_atom(self, phrase: str) -> str:
        if not phrase:
            return ''
        out = []
        for w in re.split(r'[\s,]+', phrase.strip()):
            w = w.strip('.,;:!?\'"«»()–—/\\[]{}<>').lower()
            if not w or w in _STOP_WORDS_RU:
                continue
            lemma = self._lemma_word(w)
            if lemma:
                out.append(lemma)
        return '_'.join(out)

    def _verbal_noun(self, verb_lemma: str) -> str:
        if not verb_lemma:
            return ''
        v = verb_lemma.lower()
        if v.endswith('овать'):
            return v[:-5] + 'ование'
        if v.endswith('ять') and len(v) > 4:
            return v[:-3] + 'яние'
        if v.endswith('ить') and len(v) > 4:
            return v[:-3] + 'ение'
        if v.endswith('ать') and len(v) > 4:
            return v[:-3] + 'ание'
        if v.endswith('ыть') and len(v) > 4:
            return v[:-2] + 'ытие'
        return ''

    def _verb_from_participle(self, surface: str) -> str:
        if not surface or not (self.use_pymorphy and self._morph_ru is not None):
            return ''
        try:
            for p in self._morph_ru.parse(surface.lower()):
                if p.tag.POS in ('PRTS', 'PRTF'):
                    nf = p.normal_form
                    if not nf:
                        continue
                    for p2 in self._morph_ru.parse(nf):
                        if p2.tag.POS == 'INFN' and p2.normal_form:
                            return p2.normal_form
                    return nf
        except Exception:
            pass
        return ''

    def _to_genitive(self, noun_lemma: str) -> str:
        if not noun_lemma:
            return noun_lemma
        if not (self.use_pymorphy and self._morph_ru is not None):
            return noun_lemma
        try:
            p = self._morph_ru.parse(noun_lemma)[0]
            g = p.inflect({'gent'})
            return g.word if g else noun_lemma
        except Exception:
            return noun_lemma

    def _adj_to_place_stem(self, adj_surface: str) -> Optional[str]:
        if not adj_surface:
            return None
        wl = adj_surface.lower().strip()
        for suf in (
            'ского', 'ской', 'ским', 'ские', 'ская', 'ское', 'ский',
            'цкого', 'цкой', 'цким', 'цкие', 'цкая', 'цкое', 'цкий',
        ):
            if wl.endswith(suf) and len(wl) > len(suf) + 2:
                stem = wl[:-len(suf)]
                if self.use_pymorphy and self._morph_ru is not None:
                    try:
                        for p in self._morph_ru.parse(stem):
                            if p.tag.POS in ('NOUN', 'PROPN'):
                                return p.normal_form or stem
                    except Exception:
                        pass
                return None
        return None

    def _is_ner_blacklisted_word(self, w: str) -> bool:
        if not w:
            return False
        clean = _clean_tok(w) or w
        if not clean:
            return False
        if clean in self.NER_ORG_BLACKLIST:
            return True
        if self.use_pymorphy and self._morph_ru is not None:
            try:
                for p in self._morph_ru.parse(clean):
                    if p.normal_form in self.NER_ORG_BLACKLIST:
                        return True
            except Exception:
                pass
        return False

    def _is_attr_label(self, w: str) -> bool:
        if not w:
            return False
        clean = _clean_tok(w) or w
        if not clean:
            return False
        if clean in self.ATTR_LABEL_NOUNS:
            return True
        if '_' in clean:
            for part in clean.split('_'):
                if part and part in self.ATTR_LABEL_NOUNS:
                    return True
        if self.use_pymorphy and self._morph_ru is not None:
            try:
                for p in self._morph_ru.parse(clean):
                    if p.normal_form in self.ATTR_LABEL_NOUNS:
                        return True
            except Exception:
                pass
        return False

    def _compound_has_ner_blacklisted(self, surface: str) -> bool:
        if not surface:
            return False
        if '_' not in surface and ' ' not in surface:
            return False
        parts = [p for p in re.split(r'[_\s]+', surface.strip()) if p]
        if len(parts) < 2:
            return False
        for part in parts:
            if self._is_ner_blacklisted_word(part):
                return True
        return False

    def _compound_org_blacklisted(
        self, surface: str, original: str = '',
    ) -> bool:
        return self._compound_has_ner_blacklisted(surface)

    # ==================================================================
    # noise_<lang>.txt loader
    # ==================================================================
    def _load_noise_words(self, lang: str = 'ru') -> Set[str]:
        if lang in self._noise_words_cache:
            return self._noise_words_cache[lang]
        import os as _os
        here = _os.path.dirname(_os.path.abspath(__file__))
        path = _os.path.join(here, f'noise_{lang}.txt')
        words: Set[str] = set()
        if _os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as f:
                    for line in f:
                        w = line.split('#', 1)[0].strip().lower()
                        if w:
                            words.add(w)
            except Exception:
                pass
        self._noise_words_cache[lang] = words
        return words

    # ==================================================================
    # POS-based фильтрация
    # ==================================================================
    def _is_generic_adj(self, w: str) -> bool:
        if not w:
            return True
        if w in self.GENERIC_ADJ:
            return True
        clean = _clean_tok(w) or w
        if '_' in clean:
            return False
        if _NOISE_OK:
            try:
                if is_service_word(clean, 'ru'):
                    return True
            except Exception:
                pass
            try:
                if is_service_word(clean, 'en'):
                    return True
            except Exception:
                pass
        return False

    def _is_attr_adj_noise(self, adj: str) -> bool:
        if not adj:
            return False
        clean = _clean_tok(adj) or adj
        if not clean:
            return False
        if '_' in clean:
            return True
        if clean in self.ATTR_ADJ_WHITELIST:
            return False
        noise_words = self._load_noise_words('ru')
        if clean in noise_words:
            return True
        if self.use_pymorphy and self._morph_ru is not None:
            try:
                parses = self._morph_ru.parse(clean)
            except Exception:
                return False
            if not parses:
                return False
            if all(
                hasattr(p, 'is_known') and not p.is_known for p in parses
            ):
                return True
            best = parses[0]
            if best.tag.POS in ('PRTF', 'PRTS', 'GRND', 'INFN', 'VERB'):
                return True
            if best.tag.POS not in ('ADJF', 'ADJS', 'COMP'):
                return False
            for p in parses:
                if p.normal_form and p.normal_form in self.ATTR_ADJ_WHITELIST:
                    return False
            for p in parses:
                if p.normal_form and p.normal_form in noise_words:
                    return True
            for p in parses:
                tag_str = str(p.tag)
                if 'Rel' in tag_str:
                    return True
                if 'Qual' in tag_str:
                    return False
            return False
        return False

    def _is_noise_atom(self, s: str) -> bool:
        if not s:
            return True
        clean = _clean_tok(s)
        if not clean:
            return True
        if len(clean) <= 1:
            fb = (self.FALLBACK_SUBJECT or "").lower()
            if clean != fb:
                return True
        if clean in self.OCR_ARTIFACTS:
            return True
        if _is_pure_number(clean):
            return True
        if _TEMPLATE_LEAK_RE.search(s):
            return True
        if _DOC_ID_RE.match(clean):
            return True
        s_low = s.strip().lower()
        if s_low.endswith('-') and len(s_low) > 1:
            base = _clean_tok(s_low)
            if not base or len(base) <= 2:
                return True
            if base in self.OCR_ARTIFACTS:
                return True
            if self._is_generic_adj(base):
                return True
        if len(clean) <= 4 and clean not in self.SHORT_PROTECTED:
            return True
        if len(clean) <= 12 and self.use_pymorphy and self._morph_ru is not None:
            try:
                parses = self._morph_ru.parse(clean)
            except Exception:
                parses = []
            if parses and all(
                hasattr(p, 'is_known') and not p.is_known for p in parses
            ):
                return True
        return False

    def _is_org_blacklisted(
        self,
        surface: str,
        original: str = "",
        check_pos: bool = True,
        at_sentence_start: bool = False,
        next_is_capitalized: Optional[bool] = None,
    ) -> bool:
        if not surface:
            return False
        if check_pos and _NOISE_OK:
            try:
                check_text = original or surface
                if is_common_noun_ner(
                    check_text, 'ru',
                    at_sentence_start=at_sentence_start,
                    next_is_capitalized=next_is_capitalized,
                ):
                    return True
            except Exception:
                pass
        clean = _clean_tok(surface)
        if not clean:
            return False
        for tok in clean.split('_'):
            if not tok:
                continue
            if self._is_ner_blacklisted_word(tok):
                return True
        if clean in self.SHORT_PROTECTED:
            return False
        return False

    # ==================================================================
    # Публичный API
    # ==================================================================
    def parse(
        self,
        text: str,
        lang: Optional[str] = None,
        facts_mode: str = "graph",
        query_mode: str = "graph",
        predicate: str = "user_condition",
        semantic: bool = False,
        semantic_threshold: float = 0.82,
        link_components: bool = False,
        strict: bool = False,
        log_filtered: bool = False,
        facts_from_questions: bool = True,
    ) -> Tuple[str, str]:
        if not text or not text.strip():
            return ("", "")
        self.filtered_atoms = []
        self._filtered_set = set()
        self._log_filtered_enabled = bool(log_filtered)
        if lang is None:
            lang = self._resolve_lang(text)

        text = self._strip_formulas(text)
        sentences = self._split_sentences(text)

        query_parts: List[str] = []
        all_conds: List[Term] = []

        if lang == 'ru' and self.use_natasha and sentences:
            docs = [self._build_natasha_doc(s) for s in sentences if s]
            alias_map = self._build_alias_map_from_docs(docs)
        else:
            docs = None
            alias_map = {}

        for idx, sent in enumerate(sentences):
            is_q = self._is_question(sent, lang)

            if facts_from_questions or not is_q:
                if lang == 'ru' and self.use_natasha and docs is not None:
                    conds = self._extract_from_doc(
                        docs[idx], alias_map=alias_map, strict=strict
                    ) if idx < len(docs) else []
                else:
                    conds = self.extract_conditions(sent, lang=lang)
                all_conds.extend(conds)

            if is_q:
                terms = self.extract_query(sent, lang=lang, strict=strict)
                if not terms:
                    continue
                if query_mode == "graph":
                    query_parts.append(self._to_graph_query(terms))
                elif query_mode == "raw":
                    query_parts.append(
                        ", ".join(self.term_to_prolog(t) for t in terms)
                    )
                else:
                    query_parts.append(
                        ", ".join(
                            f"user_condition({self.term_to_prolog(t)})"
                            for t in terms
                        )
                    )

        all_conds = self._dedup(all_conds, lang=lang)
        all_conds = self._postfilter_generic(all_conds)
        all_conds = self._postfilter_attr_labels(all_conds)

        seen_global: Set[str] = set()
        deduped: List[Term] = []
        for c in all_conds:
            key = self._term_key(c)
            if key in seen_global:
                continue
            seen_global.add(key)
            deduped.append(c)
        all_conds = deduped

        facts_parts: List[str] = []
        if facts_mode == "graph":
            s = self._to_graph_program(all_conds).rstrip()
            if s:
                facts_parts.append(s)
        elif facts_mode == "raw":
            for c in all_conds:
                facts_parts.append(self.term_to_prolog(c) + ".")
        else:
            for c in all_conds:
                facts_parts.append(
                    f"{predicate}({self.term_to_prolog(c)})."
                )

        if link_components and all_conds:
            link_aliases = self._build_component_aliases(all_conds, lang=lang)
            for short, canonical in link_aliases:
                key = f"alias::{short}::{canonical}"
                if key in seen_global:
                    continue
                seen_global.add(key)
                if facts_mode == "graph":
                    facts_parts.append(f"alias('{short}', '{canonical}').")
                elif facts_mode == "raw":
                    facts_parts.append(f"alias('{short}', '{canonical}').")
                else:
                    facts_parts.append(
                        f"{predicate}(alias('{short}', '{canonical}'))."
                    )

        facts_str = "\n".join(facts_parts) + ("\n" if facts_parts else "")
        query_str = ",\n".join(query_parts)
        if semantic and facts_str:
            facts_str = f":- semantic_on({semantic_threshold}).\n" + facts_str
        return (facts_str, query_str)

    def _postfilter_generic(self, conds: List[Term]) -> List[Term]:
        out: List[Term] = []
        for c in conds:
            if c.functor == 'fact' and c.arguments:
                _w = self._atom(c.arguments[0])
                if self._is_generic_adj(_w):
                    self._log_filtered(
                        self._term_desc(c),
                        f'postfilter generic_adj: {_w}')
                    continue
            elif c.functor == 'attr' and c.arguments:
                _n = self._atom(c.arguments[0])
                if self._is_generic_adj(_n):
                    self._log_filtered(
                        self._term_desc(c),
                        f'postfilter attr name generic_adj: {_n}')
                    continue
                if len(c.arguments) == 2:
                    _v = self._atom(c.arguments[1])
                    if self._is_attr_adj_noise(_v):
                        self._log_filtered(
                            self._term_desc(c),
                            f'postfilter attr value noise: {_v}')
                        continue
            elif c.functor == 'triplet' and len(c.arguments) >= 2:
                _skip = False
                _skip_reason = ''
                for i in range(1, len(c.arguments)):
                    _name = self._atom(c.arguments[i])
                    if self._is_generic_adj(_name):
                        _skip = True
                        _skip_reason = f'postfilter triplet generic_adj: {_name}'
                        break
                if _skip:
                    self._log_filtered(self._term_desc(c), _skip_reason)
                    continue
            out.append(c)
        return out

    def _postfilter_attr_labels(self, conds: List[Term]) -> List[Term]:
        if not self.ATTR_LABEL_NOUNS:
            return conds
        out: List[Term] = []
        for c in conds:
            if c.functor == 'fact' and c.arguments:
                name = self._atom(c.arguments[0])
                if self._is_attr_label(name):
                    self._log_filtered(
                        self._term_desc(c),
                        f'attr_label node: {name}')
                    continue
                out.append(c)
                continue

            if c.functor == 'attr' and len(c.arguments) >= 2:
                name = self._atom(c.arguments[0])
                if self._is_attr_label(name):
                    self._log_filtered(
                        self._term_desc(c),
                        f'attr_label attr-name: {name}')
                    continue
                out.append(c)
                continue

            if c.functor == 'triplet' and len(c.arguments) >= 2:
                pred = self._atom(c.arguments[0])
                subj = self._atom(c.arguments[1])
                subj_l = self._is_attr_label(subj)
                pred_l = self._is_attr_label(pred)

                if len(c.arguments) == 3:
                    obj = self._atom(c.arguments[2])
                    obj_l = self._is_attr_label(obj)
                    if pred == _GENITIVE_PRED and subj_l and not obj_l:
                        self._log_filtered(
                            self._term_desc(c),
                            f'attr_label invert: {subj} → {obj}')
                        out.append(Term('attr', [
                            Term(obj), Term(subj), Term('true')]))
                        continue
                    if subj_l or obj_l:
                        self._log_filtered(
                            self._term_desc(c),
                            f'attr_label triplet: '
                            f'{subj} —[{pred}]→ {obj}')
                        continue
                    out.append(c)
                    continue

                if subj_l or pred_l:
                    self._log_filtered(
                        self._term_desc(c),
                        f'attr_label triplet(2): '
                        f'{subj} —[{pred}]→ _')
                    continue
                out.append(c)
                continue

            out.append(c)
        return out

    def _build_component_aliases(
        self,
        conds: List[Term],
        lang: str,
    ) -> List[Tuple[str, str]]:
        atoms: Set[str] = set()
        for c in conds:
            if c.functor == 'triplet':
                for a in c.arguments:
                    if isinstance(a, Term) and not a.arguments:
                        atoms.add(self._atom(a))
            elif c.functor == 'attr' and c.arguments:
                atoms.add(self._atom(c.arguments[0]))
            elif c.functor == 'fact' and len(c.arguments) == 1:
                atoms.add(self._atom(c.arguments[0]))
        if not atoms:
            return []
        atom_list = sorted(atoms)
        aliases: List[Tuple[str, str]] = []
        seen_pairs: Set[Tuple[str, str]] = set()
        for a in atom_list:
            wa = a.split('_')
            for b in atom_list:
                if a == b:
                    continue
                wb = b.split('_')
                if len(wb) <= len(wa):
                    continue
                if wb[-len(wa):] == wa or wb[:len(wa)] == wa:
                    key = (a, b)
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)
                    aliases.append(key)
        return aliases

    def convert(
        self,
        text: str,
        mode: str = "condition",
        predicate: str = "user_condition",
        lang: Optional[str] = None,
    ) -> str:
        if mode == "definition":
            def_pred = "definition" if predicate == "user_condition" else predicate
            return self._convert_definition(text, predicate=def_pred)

        if mode == "query":
            terms = self.extract_query(text, lang=lang)
            if not terms:
                return ""
            return "\n".join(self.term_to_prolog(t) for t in terms)

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

    @staticmethod
    def _strip_formulas(text: str) -> str:
        text = re.sub(
            r'\n+\s*С уважением\b[^\n]*(?:\n[^\n]*)*$',
            '', text, flags=re.IGNORECASE | re.DOTALL,
        )
        text = re.sub(
            r'\n+\s*(?:Best regards|Sincerely|Yours truly)\b[^\n]*(?:\n[^\n]*)*$',
            '', text, flags=re.IGNORECASE | re.DOTALL,
        )
        return text.strip()

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        parts: List[str] = []
        current: List[str] = []
        for ch in text:
            if ch == '\n':
                s = ''.join(current).strip()
                if s:
                    parts.append(s)
                current = []
            else:
                current.append(ch)
                if ch in '.!?':
                    s = ''.join(current).strip()
                    if s:
                        parts.append(s)
                    current = []
        tail = ''.join(current).strip()
        if tail:
            parts.append(tail)
        return [s for s in parts if s]

    def _is_question(self, text: str, lang: str) -> bool:
        t = text.strip()
        if not t:
            return False
        if t.endswith('?'):
            return True
        if lang == 'ru':
            if re.search(r'\bли\b', t.lower()):
                return True
            m = re.match(r'^([а-яёa-z]+)(?=[\s,.:;!?]|$)', t.lower())
            if m and m.group(1) in _WH_LEMMAS_RU:
                return True
        else:
            m = re.match(r'^([a-z]+)(?=[\s,.:;!?]|$)', t.lower())
            if m and m.group(1) in _WH_WORDS_EN:
                return True
        return False

    def extract_query(
        self, text: str, lang: Optional[str] = None,
        strict: bool = False,
    ) -> List[Term]:
        if not text or not text.strip():
            return []
        if lang is None:
            lang = self._resolve_lang(text)
        if lang == 'ru':
            if self.use_natasha:
                try:
                    return self._extract_query_ru_natasha(
                        text, strict=strict)
                except Exception as e:
                    if self.debug:
                        print(f"[TextToProlog] query RU Natasha error: {e}")
            return self._extract_query_fallback(text, lang='ru')
        nlp = self._spacy_en if self.use_spacy else None
        if nlp is not None:
            try:
                return self._extract_query_en_spacy(text, nlp)
            except Exception as e:
                if self.debug:
                    print(f"[TextToProlog] query EN spaCy error: {e}")
        return self._extract_query_fallback(text, lang='en')

    def _build_natasha_doc(self, text: str):
        from natasha import Doc
        doc = Doc(text)
        doc.segment(_NATASHA_SEGMENTER)
        doc.tag_morph(_NATASHA_MORPH_TAGGER)
        for token in doc.tokens:
            token.lemmatize(_NATASHA_MORPH_VOCAB)
        doc.parse_syntax(_NATASHA_SYNTAX_PARSER)
        doc.tag_ner(_NATASHA_NER_TAGGER)
        return doc

    def _detect_negation_natasha(self, doc) -> bool:
        for t in doc.tokens:
            lemma = (t.lemma or '').lower()
            if lemma == 'не':
                if t.rel in ('polarity', 'neg') or t.pos == 'PART':
                    return True
            if lemma == 'нет' and t.pos in ('VERB', 'PREDICATIVE'):
                return True
        return False

    @staticmethod
    def _normalize_span(span) -> str:
        try:
            span.normalize(_NATASHA_MORPH_VOCAB)
        except Exception:
            pass
        txt = (
            getattr(span, 'normal', None)
            or getattr(span, 'norm', None)
            or span.text
        )
        parts: List[str] = []
        for p in txt.lower().split():
            p = p.strip('.,;:!?\'"«»()–—/\\[]{}<>')
            if p:
                parts.append(p)
        return "_".join(parts)

    def _build_alias_map_from_docs(self, docs) -> Dict[str, str]:
        forms: Dict[str, str] = {}
        for doc in docs:
            for span in doc.spans:
                if span.type not in ('PER', 'LOC', 'ORG'):
                    continue
                atom = self._normalize_span(span)
                if atom and atom not in forms:
                    forms[atom] = atom

        atoms = list(forms.keys())
        for a in atoms:
            wa = a.split('_')
            if len(wa) < 2:
                continue
            for b in atoms:
                if a == b:
                    continue
                wb = b.split('_')
                if len(wb) <= len(wa):
                    continue
                if wb[-len(wa):] == wa or wb[:len(wa)] == wa:
                    forms[a] = b

        def _resolve(a: str, seen: Set[str]) -> str:
            if a in seen:
                return a
            seen.add(a)
            b = forms.get(a, a)
            return a if b == a else _resolve(b, seen)

        return {a: _resolve(a, set()) for a in forms}

    def _extract_query_ru_natasha(
        self, text: str, strict: bool = False,
    ) -> List[Term]:
        # --- Грамматические фреймы (конструкция языка, не хардкод) ---
        qlow = text.strip().rstrip('?').strip().lower()
        X = Variable('X')

        # «Что такое X?» — определение
        m = re.match(r'^что\s+так(?:ое|ой)\s+(.+)$', qlow)
        if m:
            entity = self._phrase_to_atom(m.group(1))
            if entity and not self._is_noise_atom(entity):
                return [Term('fact', [Term(entity), X])]

        # «Сколько X в/на/у/при Y?» → attr(Y, 'количество_X', _)
        m = re.match(
            r'^сколько\s+([а-яё\-]+)\s+(?:в|во|на|у|при)\s+(.+)$', qlow
        )
        if m:
            count_surface = m.group(1).strip()
            entity = self._phrase_to_atom(m.group(2))
            if entity and count_surface:
                key = f"количество_{count_surface}"
                return [Term('attr', [Term(entity), Term(key), X])]

        # «Когда <participle> X?» → attr(X, 'год_<verbal_noun_gen>', _)
        m = re.match(r'^когда\s+([а-яё\-]+)\s+(.+)$', qlow)
        if m:
            verb_surface = m.group(1).strip()
            entity = self._phrase_to_atom(m.group(2))
            if entity:
                verb = (
                    self._verb_from_participle(verb_surface)
                    or self._lemma_word(verb_surface)
                )
                noun = self._verbal_noun(verb) if verb else ''
                if noun:
                    noun_gen = self._to_genitive(noun)
                    return [Term('attr', [
                        Term(entity), Term(f'год_{noun_gen}'), X,
                    ])]

        # «Есть ли X у Y?» → edge(Y, X, 'иметь') — possessive.
        m = re.match(r'^есть\s+ли\s+(.+?)\s+у\s+(.+)$', qlow)
        if m:
            obj = self._phrase_to_atom(m.group(1))
            subj = self._phrase_to_atom(m.group(2))
            if (obj and subj
                    and not self._is_noise_atom(obj)
                    and not self._is_noise_atom(subj)):
                return [Term('triplet', [
                    Term('иметь'), Term(subj), Term(obj)])]

        # --- Общий механизм: extract + wh-role ---
        doc = self._build_natasha_doc(text)
        terms = self._extract_conditions_ru_natasha(
            text, doc=doc, strict=strict,
        )

        wh_tok = None
        for t in doc.tokens:
            if t.lemma and t.lemma.lower() in _WH_LEMMAS_RU:
                wh_tok = t
                break

        negated = self._detect_negation_natasha(doc)

        if wh_tok is None:
            terms = [t for t in terms if t.functor not in ('fact', 'alias')]
            terms = self._dedup(terms, lang='ru')
            if negated:
                terms = [Term('\\+', [t]) for t in terms]
            return terms

        id_to_tok = {t.id: t for t in doc.tokens}
        wh_head = id_to_tok.get(wh_tok.head_id)
        wh_head_lemma = ((wh_head.lemma or '').lower()
                         if wh_head is not None else None)
        role = self._classify_wh_role_ru(wh_tok)
        wh_lemma = (wh_tok.lemma or '').lower()

        result: List[Term] = []

        def _name(term) -> str:
            if isinstance(term, Variable):
                return term.name
            if isinstance(term, Term):
                if term.arguments:
                    return str(term)
                return str(term.functor)
            return str(term)

        # v5.11.17: убран ранний `if role is None: result.append(term)`.
        # position-first замена subj_is_wh/obj_is_wh выполняется всегда,
        # независимо от результата _classify_wh_role_ru.
        for term in terms:
            if term.functor == 'fact':
                continue
            if term.functor == 'triplet' and len(term.arguments) == 3:
                pred, subj, obj = term.arguments
                subj_is_wh = (
                    _name(subj) == wh_lemma
                    or (wh_head_lemma and _name(subj) == wh_head_lemma)
                )
                obj_is_wh = (
                    _name(obj) == wh_lemma
                    or (wh_head_lemma and _name(obj) == wh_head_lemma)
                )
                if subj_is_wh:
                    result.append(Term('triplet', [pred, X, obj]))
                elif obj_is_wh:
                    result.append(Term('triplet', [pred, subj, X]))
                elif role == 'predicate' and wh_head_lemma and _name(pred) == wh_head_lemma:
                    result.append(Term('triplet', [X, subj, obj]))
                elif role in ('object_adverbial', 'attribute') \
                        and wh_head_lemma and _name(pred) == wh_head_lemma:
                    result.append(Term('triplet', [pred, subj, X]))
                else:
                    result.append(term)
            elif term.functor == 'triplet' and len(term.arguments) == 2:
                pred, subj = term.arguments
                subj_is_wh = (
                    _name(subj) == wh_lemma
                    or (wh_head_lemma and _name(subj) == wh_head_lemma)
                )
                if subj_is_wh:
                    result.append(Term('triplet', [pred, X]))
                elif role in ('object', 'object_adverbial', 'attribute') \
                        and wh_head_lemma and _name(pred) == wh_head_lemma:
                    result.append(Term('triplet', [pred, subj, X]))
                elif role == 'predicate' and wh_head_lemma and _name(pred) == wh_head_lemma:
                    result.append(Term('triplet', [X, subj]))
                else:
                    result.append(term)
            elif term.functor == 'attr' and len(term.arguments) == 2:
                name = term.arguments[0]
                if role == 'attribute':
                    result.append(Term('attr', [name, X]))
                else:
                    result.append(term)
            else:
                result.append(term)

        # wh-locative: локальный падеж (возвратность ⊥ локатив).
        if wh_lemma in ('где', 'куда', 'откуда'):
            _prep_map = {'где': 'в', 'куда': 'в', 'откуда': 'из'}
            _suffix = _prep_map[wh_lemma]
            _new_result: List[Term] = []
            for _term in result:
                if _term.functor == 'triplet' and len(_term.arguments) == 3:
                    _pred_atom = self._atom(_term.arguments[0])
                    if '_' not in _pred_atom:
                        _new_pred = Term(f"{_pred_atom}_{_suffix}")
                        _new_result.append(Term('triplet', [
                            _new_pred,
                            _term.arguments[1],
                            _term.arguments[2],
                        ]))
                        continue
                _new_result.append(_term)
            result = _new_result

        result = self._dedup(result, lang='ru')
        if negated:
            result = [Term('\\+', [t]) for t in result]
        return result

    def _classify_wh_role_ru(self, wh_tok) -> Optional[str]:
        lemma = (wh_tok.lemma or '').lower()
        rel = wh_tok.rel
        if rel == 'nsubj':
            return 'subject'
        if rel in ('obj', 'iobj'):
            return 'object'
        if rel == 'advmod':
            if lemma == 'как':
                return 'predicate'
            if lemma in ('где', 'когда', 'куда', 'откуда', 'почему', 'зачем'):
                return 'object_adverbial'
        if rel in ('amod', 'det'):
            return 'attribute'
        if rel == 'root' and lemma in ('кто', 'что'):
            return 'subject'
        return None

    def _detect_negation_spacy(self, doc) -> bool:
        for t in doc:
            if t.dep_ == 'neg':
                return True
            if t.lower_ in ('not', "n't") and t.dep_ in ('neg', 'advmod'):
                return True
        return False

    def _extract_query_en_spacy(self, text: str, nlp) -> List[Term]:
        doc = nlp(text)
        terms = self._extract_conditions_en_spacy(text, nlp)
        wh_tok = None
        for t in doc:
            if t.tag_ in ('WP', 'WDT', 'WRB') or t.lower_ in _WH_WORDS_EN:
                wh_tok = t
                break
        negated = self._detect_negation_spacy(doc)
        if wh_tok is None:
            terms = [t for t in terms if t.functor != 'fact']
            terms = self._dedup(terms, lang='en')
            if negated:
                terms = [Term('\\+', [t]) for t in terms]
            return terms
        role = self._classify_wh_role_en(wh_tok)
        wh_lemma = wh_tok.lemma_.lower() if wh_tok.lemma_ else wh_tok.lower_
        wh_head = wh_tok.head
        wh_head_lemma = (wh_head.lemma_.lower()
                         if wh_head is not None and wh_head.lemma_ else None)
        X = Variable('X')
        result: List[Term] = []

        def _name(term) -> str:
            if isinstance(term, Variable):
                return term.name
            if isinstance(term, Term):
                if term.arguments:
                    return str(term)
                return str(term.functor)
            return str(term)

        for term in terms:
            if term.functor == 'fact':
                continue
            if term.functor == 'triplet' and len(term.arguments) == 3:
                pred, subj, obj = term.arguments
                subj_is_wh = (
                    _name(subj) == wh_lemma
                    or (wh_head_lemma and _name(subj) == wh_head_lemma)
                )
                obj_is_wh = (
                    _name(obj) == wh_lemma
                    or (wh_head_lemma and _name(obj) == wh_head_lemma)
                )
                if subj_is_wh:
                    result.append(Term('triplet', [pred, X, obj]))
                elif obj_is_wh:
                    result.append(Term('triplet', [pred, subj, X]))
                elif role == 'predicate' and wh_head_lemma and _name(pred) == wh_head_lemma:
                    result.append(Term('triplet', [X, subj, obj]))
                elif role in ('object_adverbial',) \
                        and wh_head_lemma and _name(pred) == wh_head_lemma:
                    result.append(Term('triplet', [pred, subj, X]))
                else:
                    result.append(term)
            elif term.functor == 'triplet' and len(term.arguments) == 2:
                pred, subj = term.arguments
                subj_is_wh = (
                    _name(subj) == wh_lemma
                    or (wh_head_lemma and _name(subj) == wh_head_lemma)
                )
                if subj_is_wh:
                    result.append(Term('triplet', [pred, X]))
                elif role in ('object', 'object_adverbial') \
                        and wh_head_lemma and _name(pred) == wh_head_lemma:
                    result.append(Term('triplet', [pred, subj, X]))
                else:
                    result.append(term)
            else:
                result.append(term)
        result = self._dedup(result, lang='en')
        if negated:
            result = [Term('\\+', [t]) for t in result]
        return result

    def _classify_wh_role_en(self, wh_tok) -> Optional[str]:
        dep = wh_tok.dep_
        lemma = wh_tok.lower_
        if dep in ('nsubj', 'nsubjpass'):
            return 'subject'
        if dep in ('dobj', 'obj', 'pobj', 'dative'):
            return 'object'
        if dep == 'advmod':
            if lemma == 'how':
                return 'predicate'
            return 'object_adverbial'
        if dep in ('det', 'amod'):
            return 'attribute'
        return None

    def _extract_query_fallback(self, text: str, lang: str) -> List[Term]:
        conds = self.extract_conditions(text, lang=lang)
        return [c for c in conds if c.functor not in ('fact', 'alias')]

    def extract_conditions(
        self, text: str, lang: Optional[str] = None,
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
        self, conditions: List[Term], predicate: str = "user_condition",
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
    # RU — извлечение по предложениям
    # ==================================================================
    def _extract_conditions_ru(self, text: str) -> List[Term]:
        if self.use_natasha:
            try:
                return self._extract_conditions_ru_natasha(text)
            except Exception as e:
                if self.debug:
                    print(f"[TextToProlog] Natasha error: {e}")
        if not self.use_pymorphy or self._morph_ru is None:
            return self._extract_fallback(text, lang='ru')
        return self._extract_conditions_ru_pymorphy(text)

    def _extract_conditions_ru_natasha(
        self, text, doc=None, strict: bool = False,
    ) -> List[Term]:
        if doc is not None:
            return self._extract_from_doc(doc, alias_map=None, strict=strict)
        sentences = self._split_sentences(text)
        docs = [self._build_natasha_doc(s) for s in sentences if s]
        alias_map = self._build_alias_map_from_docs(docs)
        conditions: List[Term] = []
        for d in docs:
            conditions.extend(
                self._extract_from_doc(d, alias_map, strict=strict)
            )
        return self._dedup(conditions, lang='ru')

    def _extract_from_doc(
        self, doc, alias_map: Optional[Dict[str, str]] = None,
        strict: bool = False,
    ) -> List[Term]:
        id_to_tok: Dict[str, Any] = {t.id: t for t in doc.tokens}
        children: Dict[str, List[Any]] = {}
        for t in doc.tokens:
            children.setdefault(t.head_id, []).append(t)

        ner_id_atom: Dict[str, str] = {}
        for span in doc.spans:
            if span.type not in ('PER', 'LOC', 'ORG'):
                continue
            atom = self._normalize_span(span)
            if not atom:
                continue
            if alias_map:
                atom = alias_map.get(atom, atom)
            for t in span.tokens:
                ner_id_atom[t.id] = atom

        def _span_at_start(span) -> bool:
            if not span.tokens:
                return False
            try:
                idx = doc.tokens.index(span.tokens[0])
            except ValueError:
                return False
            if idx == 0:
                return True
            return all(
                t.pos in ('PUNCT', 'SYM', 'SPACE')
                for t in doc.tokens[:idx]
            )

        def _span_next_cap(span) -> Optional[bool]:
            if not span.tokens:
                return None
            try:
                idx_l = doc.tokens.index(span.tokens[-1])
            except ValueError:
                return None
            if not (0 <= idx_l < len(doc.tokens) - 1):
                return None
            nt = doc.tokens[idx_l + 1]
            nt_text = (nt.text or '').strip()
            if not nt_text:
                return None
            ch = nt_text[0]
            return ch.isupper() if ch.isalpha() else False

        def _is_relative_pronoun(t) -> bool:
            if t is None:
                return False
            lemma = (t.lemma or t.text or '').lower()
            return lemma in _RELATIVE_PRONOUN_LEMMAS

        compound_map: Dict[str, str] = {}

        def _tok_norm(t) -> str:
            if t.id in compound_map:
                return compound_map[t.id]
            if t.id in ner_id_atom:
                return ner_id_atom[t.id]
            lemma = (t.lemma or '').strip().lower()
            text_low = (t.text or '').strip().lower()
            if (not lemma or lemma == text_low) \
                    and self.use_pymorphy \
                    and self._morph_ru is not None \
                    and text_low:
                try:
                    parses = self._morph_ru.parse(text_low)
                    if parses and parses[0].normal_form:
                        return parses[0].normal_form
                except Exception:
                    pass
            return lemma or text_low

        def _span_atom(t) -> str:
            return _tok_norm(t)

        def _is_noun(t) -> bool:
            if _is_relative_pronoun(t):
                return False
            return t.pos in ('NOUN', 'PROPN', 'PRON', 'NPRO')

        def _is_verb(t) -> bool:
            return t.pos in ('VERB', 'AUX', 'INFN')

        def _is_passive_aux(verb_tok) -> bool:
            if verb_tok.pos != 'AUX':
                return False
            for c in children.get(verb_tok.id, []):
                if c.pos == 'VERB' and c.rel in (
                    'xcomp', 'ccomp', 'acl', 'acl:relcl'
                ):
                    return True
            return False

        def _is_proper_like(tok) -> bool:
            return tok.id in ner_id_atom or tok.pos == 'PROPN'

        def _has_case(tok) -> bool:
            return any(cc.rel == 'case' for cc in children.get(tok.id, []))

        # ============================================================
        # Compound-merge (UD): NOUN + PROPN/LOC без case.
        # ============================================================
        for _t in doc.tokens:
            if _t.id in compound_map or _t.pos != 'NOUN' or _t.id in ner_id_atom:
                continue
            for _c in children.get(_t.id, []):
                if not _is_proper_like(_c):
                    continue
                if _c.rel not in ('nmod', 'appos', 'compound'):
                    continue
                if _has_case(_c):
                    continue
                _h = _tok_norm(_t)
                _d = _tok_norm(_c)
                if not _h or not _d or _h == _d:
                    continue
                _merged = f"{_h}_{_d}"
                compound_map[_t.id] = _merged
                compound_map[_c.id] = _merged
                break

        # Rel-adj + NOUN → compound (топоним-derived).
        for _t in doc.tokens:
            if _t.id in compound_map or _t.pos != 'NOUN':
                continue
            for _c in children.get(_t.id, []):
                if _c.rel != 'amod' or _c.pos != 'ADJ':
                    continue
                if _c.id in compound_map:
                    continue
                place_stem = self._adj_to_place_stem(_c.text or '')
                if not place_stem:
                    continue
                _h = _tok_norm(_t)
                if not _h or _h == place_stem:
                    continue
                _merged = f"{_h}_{place_stem}"
                compound_map[_t.id] = _merged
                compound_map[_c.id] = _merged
                break

        def _detect_passive_voice(verb_tok):
            patient = None
            for c in children.get(verb_tok.id, []):
                if c.rel == 'nsubjpass' and not _is_relative_pronoun(c):
                    patient = c
                    break
            if patient is None:
                return (None, None)
            agent = None
            for c in children.get(verb_tok.id, []):
                if _is_relative_pronoun(c):
                    continue
                if c.rel in ('obl:agent', 'obl', 'nmod'):
                    feats = getattr(c, 'feats', None)
                    if feats is not None and 'Ins' in str(feats):
                        agent = c
                        break
                    for cc in children.get(c.id, []):
                        if cc.rel == 'case' and (cc.text or '').lower() in (
                            'кем', 'чем', 'которым', 'которой', 'которыми',
                        ):
                            agent = c
                            break
                    if agent is not None:
                        break
            return (agent, patient)

        def _subj_of(verb_tok, visited=None) -> Optional[Any]:
            if visited is None:
                visited = set()
            if verb_tok.id in visited:
                return None
            visited.add(verb_tok.id)
            for c in children.get(verb_tok.id, []):
                if c.rel == 'nsubj' and not _is_relative_pronoun(c):
                    return c
            for c in children.get(verb_tok.id, []):
                if c.rel == 'nsubj' and _is_relative_pronoun(c):
                    ante = id_to_tok.get(verb_tok.head_id)
                    if ante is not None and _is_noun(ante):
                        return ante
                    break
            for c in children.get(verb_tok.id, []):
                if (c.rel == 'iobj'
                        and not _is_relative_pronoun(c)
                        and c.pos in ('PRON', 'NPRO')):
                    return c
            if verb_tok.rel in ('xcomp', 'advcl', 'ccomp'):
                parent = id_to_tok.get(verb_tok.head_id)
                if parent is not None and _is_verb(parent):
                    return _subj_of(parent, visited)
            if verb_tok.rel in ('acl', 'acl:relcl'):
                parent = id_to_tok.get(verb_tok.head_id)
                if parent is not None and _is_noun(parent):
                    return parent
                if parent is not None and _is_verb(parent):
                    return _subj_of(parent, visited)

            # wh-pronoun at root — semantic subject
            for cand in doc.tokens:
                if (cand.rel == 'root'
                        and (cand.lemma or '').lower() in ('кто', 'что')):
                    return cand

            # v5.11.19: fallback для Natasha self-loop
            # (amod head=self на preverbal NOUN, qa_026).
            # Ищем NOUN-кандидата с ОБЕИХ сторон от root-verb:
            #   backward — канонический SVO;
            #   forward  — VS-инверсия.
            if verb_tok.rel == 'root':
                try:
                    verb_idx = doc.tokens.index(verb_tok)
                except ValueError:
                    verb_idx = -1

                def _cand_ok(c):
                    if c.pos not in ('NOUN', 'PROPN'):
                        return False
                    if _is_relative_pronoun(c):
                        return False
                    if any(cc.rel == 'case'
                           for cc in children.get(c.id, [])):
                        return False
                    if c.rel in ('obl', 'nmod', 'obj', 'iobj'):
                        return False
                    return True

                for k in range(verb_idx - 1,
                               max(-1, verb_idx - 6), -1):
                    cand = doc.tokens[k]
                    if _cand_ok(cand):
                        return cand
                for k in range(verb_idx + 1,
                               min(len(doc.tokens), verb_idx + 6)):
                    cand = doc.tokens[k]
                    if _cand_ok(cand):
                        return cand

            return None

        def _obj_of(verb_tok, exclude_id: Optional[str] = None):
            """Возвращает (obj_tok, prep). prep=None если obj прямой."""
            for c in children.get(verb_tok.id, []):
                if c.rel == 'obj' and not _is_relative_pronoun(c):
                    if _span_atom(c) not in _STOP_WORDS_RU:
                        return (c, None)
            for c in children.get(verb_tok.id, []):
                if c.rel == 'obj' and _is_relative_pronoun(c):
                    ante = id_to_tok.get(verb_tok.head_id)
                    if ante is not None and _is_noun(ante):
                        return (ante, None)
                    break
            for c in children.get(verb_tok.id, []):
                if (c.rel == 'iobj'
                        and c.id != exclude_id
                        and not _is_relative_pronoun(c)
                        and _span_atom(c) not in _STOP_WORDS_RU):
                    return (c, None)
            for c in children.get(verb_tok.id, []):
                if c.rel in ('nmod', 'obl'):
                    if _is_relative_pronoun(c):
                        continue
                    if _span_atom(c) in _STOP_WORDS_RU:
                        continue
                    if (c.lemma or '').lower() in self.TEMPORAL_PLACE_LEMMAS:
                        continue
                    case_tok = None
                    for cc in children.get(c.id, []):
                        if cc.rel == 'case':
                            case_tok = cc
                            break
                    if case_tok is None:
                        continue
                    prep = (case_tok.text or '').lower()
                    if prep in _ADVERBIAL_PREPS:
                        if (prep in ('с', 'со')
                                and (verb_tok.lemma or '').lower()
                                    in self.SOCIATIVE_HEADS):
                            return (c, prep)
                        continue
                    if prep in _OBJECT_PREPS:
                        return (c, prep)
            return (None, None)

        def _obj_has_wh_amod(obj_tok) -> bool:
            if obj_tok is None:
                return False
            for cc in children.get(obj_tok.id, []):
                if cc.rel in ('amod', 'det'):
                    lemma = (cc.lemma or cc.text or '').lower()
                    if lemma in _WH_LEMMAS_RU:
                        return True
            return False

        conditions: List[Term] = []
        used_ids: Set[str] = set()

        # ============================================================
        # 1. Глаголы → triplet
        # ============================================================
        for t in doc.tokens:
            if not _is_verb(t) or t.id in used_ids:
                continue
            if _is_passive_aux(t):
                used_ids.add(t.id)
                continue
            pred = _tok_norm(t)
            if pred in _STOP_WORDS_RU or pred in _MODAL_VERBS_RU:
                continue
            if self._is_noise_atom(pred):
                used_ids.add(t.id)
                continue
            if (t.lemma or '').lower() in ('звать', 'называть', 'называться'):
                per_span = next(
                    (s for s in doc.spans if s.type == 'PER'), None
                )
                if per_span is not None:
                    ner_atom = self._normalize_span(per_span)
                    if alias_map:
                        ner_atom = alias_map.get(ner_atom, ner_atom)
                    if ner_atom and not self._is_noise_atom(ner_atom):
                        obj_tok, _ = _obj_of(t)
                        person = "я"
                        if obj_tok is not None:
                            cand = _span_atom(obj_tok)
                            if cand not in _STOP_WORDS_RU:
                                person = cand
                        conditions.append(Term('attr', [
                            Term(person), Term('name'), Term(ner_atom)]))
                        used_ids.add(t.id)
                        if obj_tok is not None:
                            used_ids.add(obj_tok.id)
                        for st in per_span.tokens:
                            used_ids.add(st.id)
                        continue
            agent_tok, patient_tok = _detect_passive_voice(t)
            if patient_tok is not None:
                obj = _span_atom(patient_tok)
                if obj in _STOP_WORDS_RU or self._is_noise_atom(obj):
                    obj = None
                if agent_tok is not None:
                    subj = _span_atom(agent_tok)
                    if subj in _STOP_WORDS_RU or self._is_noise_atom(subj):
                        subj = "?"
                    used_ids.add(agent_tok.id)
                else:
                    subj = "?"
                if subj is not None and obj is not None and obj != subj:
                    conditions.append(Term('triplet', [
                        Term(pred), Term(subj), Term(obj)]))
                    used_ids.add(patient_tok.id)
                used_ids.add(t.id)
                continue
            subj_tok = _subj_of(t)
            subj_exclude = subj_tok.id if subj_tok is not None else None
            obj_tok, obj_prep = _obj_of(t, exclude_id=subj_exclude)
            if obj_tok is not None and _is_relative_pronoun(obj_tok):
                obj_tok = None
                obj_prep = None

            # Ins-объект + переходный глагол → пассивно-возвратная диатеза.
            if obj_tok is not None and obj_prep is None:
                _feats = getattr(obj_tok, 'feats', None)
                if (_feats is not None and 'Ins' in str(_feats)
                        and not pred.endswith('ся')
                        and pred.endswith('ть')):
                    reflex = pred + 'ся'
                    obj_atom = _span_atom(obj_tok)
                    _subj_atom = (
                        _span_atom(subj_tok) if subj_tok is not None
                        else self.FALLBACK_SUBJECT
                    )
                    if (obj_atom and obj_atom != _subj_atom
                            and not self._is_noise_atom(obj_atom)
                            and obj_atom not in _STOP_WORDS_RU
                            and _subj_atom):
                        conditions.append(Term('triplet', [
                            Term(reflex),
                            Term(obj_atom),
                            Term(_subj_atom),
                        ]))
                        used_ids.add(obj_tok.id)
                        used_ids.add(t.id)
                        if subj_tok is not None:
                            used_ids.add(subj_tok.id)
                        continue

            if subj_tok is not None:
                subj = _span_atom(subj_tok)
                if subj in _WH_LEMMAS_RU:
                    pass
                elif _is_relative_pronoun(subj_tok):
                    if strict or self.FALLBACK_SUBJECT is None:
                        used_ids.add(t.id)
                        continue
                    subj = self.FALLBACK_SUBJECT
                elif subj in _STOP_WORDS_RU and subj != 'я':
                    if strict or self.FALLBACK_SUBJECT is None:
                        used_ids.add(t.id)
                        continue
                    subj = self.FALLBACK_SUBJECT
                elif self._is_noise_atom(subj):
                    used_ids.add(t.id)
                    continue
            else:
                if strict or self.FALLBACK_SUBJECT is None:
                    used_ids.add(t.id)
                    continue
                subj = self.FALLBACK_SUBJECT

            pred_final = f"{pred}_{obj_prep}" if obj_prep else pred

            if obj_tok is not None:
                if _obj_has_wh_amod(obj_tok):
                    conditions.append(Term('triplet', [
                        Term(pred_final), Term(subj), Variable('X')]))
                    used_ids.add(obj_tok.id)
                    used_ids.add(t.id)
                    if subj_tok is not None:
                        used_ids.add(subj_tok.id)
                    continue
                obj = _span_atom(obj_tok)
                if obj in _STOP_WORDS_RU or obj == subj or self._is_noise_atom(obj):
                    obj_tok = None
                else:
                    conditions.append(Term('triplet', [
                        Term(pred_final), Term(subj), Term(obj)]))
                    used_ids.add(obj_tok.id)
            if obj_tok is None:
                conditions.append(Term('triplet', [Term(pred_final), Term(subj)]))
            used_ids.add(t.id)
            if subj_tok is not None:
                used_ids.add(subj_tok.id)

        # ============================================================
        # 2b. WH-amod ATTR
        # ============================================================
        for t in doc.tokens:
            if t.id in used_ids or t.pos != 'NOUN':
                continue
            if t.rel not in ('root', 'nsubj', 'xcomp', 'conj'):
                continue
            wh_amod = None
            for c in children.get(t.id, []):
                if c.rel in ('amod', 'det'):
                    lemma = (c.lemma or c.text or '').lower()
                    if lemma in _WH_LEMMAS_RU:
                        wh_amod = c
                        break
            if wh_amod is None:
                continue

            obj_tok = None
            for c in children.get(t.id, []):
                if c.rel not in ('nmod', 'obl'):
                    continue
                has_target_case = False
                for cc in children.get(c.id, []):
                    if cc.rel == 'case':
                        prep = (cc.text or '').lower()
                        if prep in _OBJECT_PREPS or prep == 'у':
                            has_target_case = True
                            break
                if 'Gen' in str(getattr(c, 'feats', '')):
                    has_target_case = True
                if has_target_case:
                    obj_tok = c
                    break
            if obj_tok is None:
                continue

            entity = _span_atom(obj_tok)
            wh_lemma_am = (wh_amod.lemma or wh_amod.text or '').lower()

            if wh_lemma_am == 'сколько':
                attr_surface = (t.text or '').strip().lower()
                attr_key = f"количество_{attr_surface}"
            else:
                attr_key = _span_atom(t)

            if (not entity or not attr_key
                    or entity in _STOP_WORDS_RU
                    or attr_key in _STOP_WORDS_RU
                    or self._is_noise_atom(entity)
                    or self._is_noise_atom(attr_key)):
                continue
            conditions.append(Term('attr', [
                Term(entity), Term(attr_key), Variable('X')]))
            used_ids.add(t.id)
            used_ids.add(obj_tok.id)
            used_ids.add(wh_amod.id)

        # ============================================================
        # 2. attr (amod) — обычные прилагательные (не WH, не compound)
        # ============================================================
        for t in doc.tokens:
            if t.rel != 'amod':
                continue
            if t.id in used_ids:
                continue
            if t.id in compound_map:
                continue
            head = id_to_tok.get(t.head_id)
            if head is None or head.id in used_ids or not _is_noun(head):
                continue
            if t.pos != 'ADJ':
                continue
            if (t.lemma or '').lower() in _WH_LEMMAS_RU:
                continue
            adj_clean = _clean_tok((t.text or ''))
            if adj_clean not in self.ATTR_ADJ_WHITELIST:
                if (self.use_pymorphy and self._morph_ru is not None
                        and adj_clean):
                    try:
                        parses = self._morph_ru.parse(adj_clean)
                        if parses:
                            best = parses[0]
                            if best.tag.POS in ('PRTF', 'PRTS', 'GRND',
                                                'INFN', 'VERB'):
                                continue
                            if best.tag.POS not in ('ADJF', 'ADJS', 'COMP'):
                                continue
                    except Exception:
                        pass
            if _is_relative_pronoun(t) or _is_relative_pronoun(head):
                continue
            if (t.id in ner_id_atom and head.id in ner_id_atom
                    and ner_id_atom[t.id] == ner_id_atom[head.id]):
                continue
            adj = _tok_norm(t)
            noun = _span_atom(head)
            if adj in _ADJ_STOP_WORDS_RU or noun in _STOP_WORDS_RU:
                continue
            if adj == noun:
                continue
            if self._is_generic_adj(noun):
                continue
            if self._is_attr_adj_noise(adj):
                continue
            if self._compound_has_ner_blacklisted(adj):
                continue
            if self._compound_has_ner_blacklisted(noun):
                continue
            if self._is_noise_atom(adj) or self._is_noise_atom(noun):
                continue
            conditions.append(Term('attr', [Term(noun), Term(adj)]))
            used_ids.add(t.id)
            used_ids.add(head.id)

        # ============================================================
        # 3. nmod + Case=Gen → of / role-triple
        # ============================================================
        seen_of: Set[Tuple[str, str]] = set()
        for t in doc.tokens:
            if t.rel != 'nmod':
                continue
            head = id_to_tok.get(t.head_id)
            if head is None or not _is_noun(head):
                continue
            if _is_relative_pronoun(head) or _is_relative_pronoun(t):
                continue
            head_norm = _tok_norm(head)
            if head_norm in _RELATIONAL_NOUNS:
                continue
            if head_norm in self.SKIP_LEFTOVER_NOUNS:
                continue
            if head_norm in self.TEMPORAL_PLACE_LEMMAS:
                continue
            if self._is_generic_adj(head_norm):
                continue
            if self._is_noise_atom(head_norm):
                continue
            feats = getattr(t, 'feats', None)
            case_gen = feats is not None and 'Gen' in str(feats)
            if not case_gen:
                for cc in children.get(t.id, []):
                    if cc.rel == 'case' and cc.text.lower() in ('из', 'от', 'с'):
                        case_gen = True
                        break
            if not case_gen:
                continue
            dep = _span_atom(t)
            if _is_pure_number(dep) or dep in self.OCR_ARTIFACTS:
                continue
            if self._is_generic_adj(dep):
                continue
            if self._is_noise_atom(dep):
                continue
            h = head_norm
            if dep == h or dep in _STOP_WORDS_RU or h in _STOP_WORDS_RU:
                continue

            role_subj = None
            for c in children.get(head.id, []):
                if c.rel == 'nsubj':
                    role_subj = c
                    break

            if role_subj is None:
                parent = id_to_tok.get(head.head_id)
                if parent is not None and (
                    (parent.lemma or '').lower() in _WH_LEMMAS_RU
                ):
                    role_subj = parent
                elif parent is not None and head.rel in (
                    'xcomp', 'parataxis', 'ccomp', 'acl:relcl',
                    'nmod', 'appos',
                ):
                    for c in children.get(parent.id, []):
                        if c.rel in ('nsubj', 'nsubjpass'):
                            role_subj = c
                            break
                    if (role_subj is None and _is_noun(parent)
                            and parent.id not in used_ids):
                        role_subj = parent

            if role_subj is not None:
                subj_atom = _span_atom(role_subj)
                role_subj_is_wh = (role_subj.lemma or '').lower() in _WH_LEMMAS_RU
                allowed = (role_subj.id not in used_ids) or role_subj_is_wh
                if (allowed
                        and (subj_atom not in _STOP_WORDS_RU
                             or subj_atom in _WH_LEMMAS_RU)):
                    conditions.append(Term('triplet', [
                        Term(h), Term(subj_atom), Term(dep)]))
                    used_ids.add(t.id)
                    used_ids.add(head.id)
                    used_ids.add(role_subj.id)
                    conditions = [
                        c for c in conditions
                        if not (c.functor == 'attr' and len(c.arguments) >= 2
                                and self._atom(c.arguments[0]) == dep
                                and isinstance(c.arguments[-1], Variable))
                    ]
                    continue

            already_handled = any(
                c.functor == 'attr' and len(c.arguments) >= 2
                and self._atom(c.arguments[0]) == dep
                for c in conditions
            )
            if already_handled:
                continue

            key = (h, dep)
            if key in seen_of:
                continue
            seen_of.add(key)
            conditions.append(Term('triplet', [
                Term(_GENITIVE_PRED), Term(h), Term(dep)]))
            used_ids.add(t.id)
            used_ids.add(head.id)

        # ============================================================
        # 4. Копула
        # ============================================================
        for t in doc.tokens:
            if t.id in used_ids:
                continue
            if t.pos not in ('NOUN', 'PROPN'):
                continue
            if t.rel not in ('root', 'xcomp', 'acl', 'acl:relcl',
                             'parataxis'):
                continue
            subj = None
            for c in children.get(t.id, []):
                if c.rel == 'nsubj' and not _is_relative_pronoun(c):
                    subj = c
                    break
            if subj is None or subj.id in used_ids:
                continue
            h = _span_atom(subj)
            d = _span_atom(t)
            if h in _STOP_WORDS_RU or d in _STOP_WORDS_RU or h == d:
                continue
            if self._is_noise_atom(h) or self._is_noise_atom(d):
                continue
            conditions.append(Term('triplet', [
                Term('являться'), Term(h), Term(d)]))
            used_ids.add(t.id)
            used_ids.add(subj.id)

        # ============================================================
        # 5. «X, как Y»
        # ============================================================
        for span in doc.spans:
            if span.type != 'PER':
                continue
            if any(t.id in used_ids for t in span.tokens):
                continue
            first_tok = span.tokens[0]
            try:
                idx = doc.tokens.index(first_tok)
            except ValueError:
                continue
            found_noun = None
            how_idx = -1
            for k in range(idx - 1, max(-1, idx - 6), -1):
                tok = doc.tokens[k]
                if (tok.lemma or '').lower() == 'как':
                    how_idx = k
                    break
            if how_idx < 0:
                continue
            for j in range(how_idx - 1, max(-1, how_idx - 4), -1):
                prev = doc.tokens[j]
                if prev.id in used_ids:
                    continue
                if prev.id in ner_id_atom:
                    continue
                if prev.pos in ('NOUN', 'PROPN') and _is_noun(prev):
                    found_noun = prev
                    break
            if found_noun is None:
                continue
            ner_atom = self._normalize_span(span)
            if alias_map:
                ner_atom = alias_map.get(ner_atom, ner_atom)
            noun_atom = _span_atom(found_noun)
            if not ner_atom or not noun_atom:
                continue
            if noun_atom in _STOP_WORDS_RU:
                continue
            if noun_atom == ner_atom:
                continue
            if self._is_noise_atom(ner_atom) or self._is_noise_atom(noun_atom):
                continue
            conditions.append(Term('triplet', [
                Term('являться'), Term(ner_atom), Term(noun_atom)]))
            for st in span.tokens:
                used_ids.add(st.id)
            used_ids.add(found_noun.id)

        # ============================================================
        # 6. «NOUN «NER»»
        # ============================================================
        for span in doc.spans:
            if span.type not in ('ORG', 'PRODUCT'):
                continue
            first_tok = span.tokens[0]
            try:
                idx = doc.tokens.index(first_tok)
            except ValueError:
                continue
            prev = None
            has_quotes = False
            for j in range(idx - 1, max(-1, idx - 4), -1):
                tok = doc.tokens[j]
                if tok.id in ner_id_atom:
                    break
                if tok.pos in ('NOUN', 'PROPN'):
                    prev = tok
                    break
                if tok.pos in ('PUNCT', 'SYM'):
                    if tok.text in ('«', '»', '"', '“', '”', "'"):
                        has_quotes = True
                    continue
                break
            if prev is None or prev.id in used_ids:
                continue
            noun_atom = _span_atom(prev)
            ner_atom = self._normalize_span(span)
            if alias_map:
                ner_atom = alias_map.get(ner_atom, ner_atom)
            if not noun_atom or not ner_atom:
                continue
            if noun_atom in _STOP_WORDS_RU:
                continue
            if noun_atom == ner_atom:
                continue
            if self._is_noise_atom(noun_atom) or self._is_noise_atom(ner_atom):
                continue
            if self._is_generic_adj(noun_atom):
                continue
            span_at_start = _span_at_start(span)
            span_next_cap = _span_next_cap(span)
            span_orig = getattr(span, 'text', '') or ''
            if self._is_org_blacklisted(
                ner_atom, original=span_orig,
                at_sentence_start=span_at_start,
                next_is_capitalized=span_next_cap,
            ):
                continue
            if self._compound_has_ner_blacklisted(ner_atom):
                continue
            if not has_quotes:
                feats = getattr(first_tok, 'feats', None)
                if feats is not None and 'Gen' in str(feats):
                    continue
            conditions.append(Term('attr', [
                Term(noun_atom), Term('name'), Term(ner_atom)]))
            used_ids.add(prev.id)

        # ============================================================
        # 7. Социативные существительные
        # ============================================================
        for t in doc.tokens:
            if t.id in used_ids:
                continue
            if t.pos not in ('NOUN', 'PROPN'):
                continue
            if (t.lemma or '').lower() not in self.SOCIATIVE_HEADS:
                continue
            for c in children.get(t.id, []):
                if c.rel not in ('nmod', 'obl'):
                    continue
                if _is_relative_pronoun(c):
                    continue
                case_tok = None
                for cc in children.get(c.id, []):
                    if cc.rel == 'case':
                        case_tok = cc
                        break
                if case_tok is None:
                    continue
                if case_tok.text.lower() not in ('с', 'со'):
                    continue
                if _span_atom(c) in _STOP_WORDS_RU or c.id in used_ids:
                    continue
                if self._is_noise_atom(_span_atom(t)) or self._is_noise_atom(_span_atom(c)):
                    continue
                conditions.append(Term('triplet', [
                    Term('of'), Term(_span_atom(t)), Term(_span_atom(c))]))
                used_ids.add(c.id)

        # ============================================================
        # 8. Сочинение (conj)
        # ============================================================
        conj_additions: List[Tuple[str, str, str, str]] = []
        seen_conj: Set[str] = set()
        for t in doc.tokens:
            if t.rel != 'conj':
                continue
            if t.id in seen_conj or t.id in used_ids:
                continue
            head_tok = id_to_tok.get(t.head_id)
            if head_tok is None or head_tok.id not in used_ids:
                continue
            head_atom = _span_atom(head_tok)
            conj_atom = _span_atom(t)
            if not head_atom or not conj_atom or head_atom == conj_atom:
                continue
            if conj_atom in _STOP_WORDS_RU:
                continue
            if self._is_noise_atom(conj_atom):
                continue
            for c in conditions:
                if c.functor != 'triplet' or len(c.arguments) != 3:
                    continue
                pred_name = self._atom(c.arguments[0])
                subj_name = self._atom(c.arguments[1])
                obj_name = self._atom(c.arguments[2])
                if subj_name == head_atom:
                    if conj_atom == obj_name:
                        continue
                    conj_additions.append(
                        (pred_name, conj_atom, obj_name, t.id))
                elif obj_name == head_atom:
                    if conj_atom == subj_name:
                        continue
                    conj_additions.append(
                        (pred_name, subj_name, conj_atom, t.id))
        for pred_name, subj_name, obj_name, tok_id in conj_additions:
            conditions.append(Term('triplet', [
                Term(pred_name), Term(subj_name), Term(obj_name)]))
            seen_conj.add(tok_id)
            used_ids.add(tok_id)

        # ============================================================
        # 9. NER-факты + alias/2
        # ============================================================
        for span in doc.spans:
            if span.type not in ('PER', 'LOC', 'ORG'):
                continue
            surface = self._normalize_span(span)
            if (not surface
                    or surface in _STOP_WORDS_RU
                    or surface in _STOP_WORDS_EN):
                continue
            if _is_pure_number(surface) or _clean_tok(surface) in self.OCR_ARTIFACTS:
                continue
            if _TEMPLATE_LEAK_RE.search(surface):
                continue
            if self._is_noise_atom(surface):
                continue
            canonical = alias_map.get(surface, surface) if alias_map else surface
            if _TEMPLATE_LEAK_RE.search(canonical):
                continue
            if self._is_noise_atom(canonical):
                continue
            if self._is_generic_adj(canonical):
                continue
            gtype = _NER_TO_GRAPH_TYPE.get(span.type)

            span_at_start = _span_at_start(span)
            span_next_cap = _span_next_cap(span)
            span_orig = getattr(span, 'text', '') or ''

            if self._compound_has_ner_blacklisted(canonical):
                gtype = 'concept' if gtype is not None else gtype

            if gtype is not None and self._is_org_blacklisted(
                canonical, original=span_orig,
                at_sentence_start=span_at_start,
                next_is_capitalized=span_next_cap,
            ):
                gtype = 'concept'

            if gtype is not None:
                conditions.append(Term('fact', [Term(canonical), Term(gtype)]))
            elif not all(t.id in used_ids for t in span.tokens):
                conditions.append(Term('fact', [Term(canonical)]))
            if canonical != surface:
                conditions.append(Term('alias', [Term(surface), Term(canonical)]))
            for t in span.tokens:
                used_ids.add(t.id)

        # ============================================================
        # 10. Прочие существительные → fact
        # ============================================================
        for t in doc.tokens:
            if not _is_noun(t) or t.id in used_ids:
                continue
            if t.id in ner_id_atom:
                continue
            if _is_relative_pronoun(t):
                continue
            lemma = _tok_norm(t)
            if lemma in _STOP_WORDS_RU or lemma in _ADJ_STOP_WORDS_RU:
                continue
            if self._is_generic_adj(lemma):
                continue
            if self._is_noise_atom(lemma):
                continue
            if t.rel in ('nmod', 'obl'):
                case_tok = None
                for cc in children.get(t.id, []):
                    if cc.rel == 'case':
                        case_tok = cc
                        break
                if case_tok is not None and case_tok.text.lower() in _ADVERBIAL_PREPS:
                    continue
            if lemma in self.SKIP_LEFTOVER_NOUNS:
                continue
            if lemma in self.TEMPORAL_PLACE_LEMMAS:
                continue
            conditions.append(Term('fact', [Term(lemma)]))
            used_ids.add(t.id)

        return conditions

    # ==================================================================
    # RU — pymorphy3 fallback
    # ==================================================================
    def _extract_conditions_ru_pymorphy(self, text: str) -> List[Term]:
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
            if t.get('is_ner'):
                return True
            p = t['parse']
            if p is None:
                return False
            if p.tag.POS in ('NOUN', 'NPRO'):
                return p.normal_form not in _RELATIVE_PRONOUN_LEMMAS
            return 'LATN' in str(p.tag).upper()

        def _is_adj(t):
            return t['parse'] is not None and t['parse'].tag.POS in ('ADJF', 'ADJS')

        def _has_nomn(t):
            if t.get('is_ner'):
                return True
            p = t['parse']
            if p is None:
                return False
            if 'nomn' in p.tag:
                return True
            try:
                return any('nomn' in pp.tag for pp in self._morph_ru.parse(t['word']))
            except Exception:
                return False

        def _is_stop_adj(t):
            return (t['word'] in _ADJ_STOP_WORDS_RU
                    or t['norm'] in _ADJ_STOP_WORDS_RU)

        def _find_subject(idx):
            for j in range(max(0, idx - 3), idx):
                if j in used:
                    continue
                t = tokens[j]
                if t['is_span_tail']:
                    continue
                if _is_noun(t) and (_has_nomn(t) or 'LATN' in str(t['parse'].tag).upper()):
                    return j
            return None

        def _find_object_after(verb_idx):
            skip = []
            for k in range(verb_idx + 1, min(len(tokens), verb_idx + 6)):
                tk = tokens[k]
                if tk['is_span_tail'] or k in used:
                    continue
                if not _is_noun(tk):
                    continue
                if tk['norm'] in self.TEMPORAL_PLACE_LEMMAS:
                    continue
                if tk['norm'] in _RELATIONAL_NOUNS:
                    skip.append(k)
                    for kk in range(k + 1, min(len(tokens), k + 4)):
                        tk2 = tokens[kk]
                        if tk2['is_span_tail'] or kk in used:
                            continue
                        if _is_noun(tk2):
                            return kk, tk2['norm'], skip
                    return k, tk['norm'], skip
                return k, tk['norm'], skip
            return None, None, skip

        conditions = []
        used = set()
        last_subject = None

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
                action_idx = None
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
                    if subj_idx is not None:
                        subj_norm = tokens[subj_idx]['norm']
                        last_subject = subj_norm
                    else:
                        subj_norm = last_subject or "я"
                    obj_idx, obj_norm, skips = _find_object_after(action_idx)
                    for s in skips:
                        used.add(s)
                    if obj_norm is not None:
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
                    j = action_idx + 1
                    while j < len(tokens):
                        tj = tokens[j]
                        if tj['is_span_tail'] or tj['word'] in ('или', 'и', 'либо'):
                            j += 1
                            continue
                        if _is_verb(tj):
                            if obj_norm is not None:
                                conditions.append(Term('triplet', [
                                    Term(tj['norm']), Term(subj_norm),
                                    Term(obj_norm)]))
                            else:
                                conditions.append(Term('triplet', [
                                    Term(tj['norm']), Term(subj_norm)]))
                            used.add(j)
                            j += 1
                            continue
                        break
                    i = j
                    continue
                used.add(i)
                i += 1
                continue
            subj_idx = _find_subject(i)
            pred_norm = tok['norm']
            if subj_idx is not None:
                subj_norm = tokens[subj_idx]['norm']
                last_subject = subj_norm
            else:
                subj_norm = last_subject or "я"
            obj_idx, obj_norm, skips = _find_object_after(i)
            for s in skips:
                used.add(s)
            if obj_norm is not None:
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

        for k in range(len(tokens) - 1):
            t1, t2 = tokens[k], tokens[k + 1]
            if t1['is_span_tail'] or t2['is_span_tail']:
                continue
            if k in used or (k + 1) in used:
                continue
            if _is_stop_adj(t1) or _is_stop_adj(t2):
                continue
            if _is_noun(t1) and _is_adj(t2):
                adj = t2['norm']
                if self._is_generic_adj(t1['norm']):
                    continue
                if self._is_attr_adj_noise(adj):
                    continue
                if self._is_noise_atom(t1['norm']) or self._is_noise_atom(adj):
                    continue
                conditions.append(Term('attr', [Term(t1['norm']), Term(adj)]))
                used.add(k); used.add(k + 1)
            elif _is_adj(t1) and _is_noun(t2):
                adj = t1['norm']
                if self._is_generic_adj(t2['norm']):
                    continue
                if self._is_attr_adj_noise(adj):
                    continue
                if self._is_noise_atom(t2['norm']) or self._is_noise_atom(adj):
                    continue
                conditions.append(Term('attr', [Term(t2['norm']), Term(adj)]))
                used.add(k); used.add(k + 1)

        for k in range(len(tokens) - 1):
            t1, t2 = tokens[k], tokens[k + 1]
            if t1['is_span_tail'] or t2['is_span_tail']:
                continue
            if k in used or (k + 1) in used:
                continue
            if (_is_noun(t1) and _has_nomn(t1)
                    and _is_noun(t2) and _has_nomn(t2)):
                conditions.append(Term('fact', [
                    Term(f"{t1['norm']}_{t2['norm']}")]))
                used.add(k); used.add(k + 1)

        for k in range(len(tokens) - 1):
            t1 = tokens[k]
            if t1['is_span_tail']:
                continue
            if not _is_noun(t1):
                continue
            if t1['norm'] in _RELATIONAL_NOUNS:
                continue
            if t1['norm'] in self.SKIP_LEFTOVER_NOUNS:
                continue
            if t1['norm'] in self.TEMPORAL_PLACE_LEMMAS:
                continue
            if self._is_generic_adj(t1['norm']):
                continue
            if self._is_noise_atom(t1['norm']):
                continue
            j = k + 1
            while j < len(tokens) and _is_adj(tokens[j]):
                if tokens[j]['is_span_tail']:
                    break
                j += 1
            if j >= len(tokens):
                continue
            tj = tokens[j]
            if tj['is_span_tail']:
                continue
            if not _is_noun(tj) or tj['parse'] is None:
                continue
            if 'gent' not in tj['parse'].tag:
                continue
            head_norm = t1['norm']
            tail_norm = tj['norm']
            if head_norm == tail_norm:
                continue
            if self._is_generic_adj(tail_norm):
                continue
            if _is_pure_number(tail_norm) or self._is_noise_atom(tail_norm):
                continue
            conditions.append(Term('triplet', [
                Term(_GENITIVE_PRED), Term(head_norm), Term(tail_norm)]))
            used.add(k); used.add(j)
            jj = j + 1
            while jj < len(tokens) - 1:
                if tokens[jj]['is_span_tail']:
                    break
                if tokens[jj]['word'] not in ('и', 'или', 'либо'):
                    break
                jj += 1
                while jj < len(tokens) and _is_adj(tokens[jj]):
                    if tokens[jj]['is_span_tail']:
                        break
                    jj += 1
                if jj >= len(tokens):
                    break
                tjj = tokens[jj]
                if tjj['is_span_tail']:
                    break
                if not _is_noun(tjj) or tjj['parse'] is None:
                    break
                if 'gent' not in tjj['parse'].tag:
                    break
                tail2_norm = tjj['norm']
                if tail2_norm == head_norm:
                    break
                if self._is_generic_adj(tail2_norm):
                    break
                conditions.append(Term('triplet', [
                    Term(_GENITIVE_PRED), Term(head_norm), Term(tail2_norm)]))
                used.add(jj)
                jj += 1

        for k, tok in enumerate(tokens):
            if k in used or tok['is_span_tail']:
                continue
            if not _is_noun(tok):
                p = tok['parse']
                if p is None or p.tag.POS not in ('ADJF', 'ADJS'):
                    continue
            if (tok['word'] in _STOP_WORDS_RU
                    or tok['word'] in _ADJ_STOP_WORDS_RU
                    or tok['norm'] in _ADJ_STOP_WORDS_RU):
                continue
            if self._is_generic_adj(tok['norm']):
                continue
            if tok['norm'] in self.SKIP_LEFTOVER_NOUNS:
                continue
            if tok['norm'] in self.TEMPORAL_PLACE_LEMMAS:
                continue
            if self._is_noise_atom(tok['norm']):
                continue
            conditions.append(Term('fact', [Term(tok['norm'])]))
            used.add(k)

        for k, tok in enumerate(tokens):
            if not tok.get('is_ner'):
                continue
            gtype = tok.get('ner_type')
            if gtype is None:
                continue
            atom = tok.get('ner_atom')
            if not atom or atom in _STOP_WORDS_RU:
                continue
            if _is_pure_number(atom) or _clean_tok(atom) in self.OCR_ARTIFACTS:
                continue
            if _TEMPLATE_LEAK_RE.search(atom):
                continue
            if self._is_noise_atom(atom):
                continue
            if self._is_generic_adj(atom):
                continue
            orig = tok.get('ner_orig', atom)
            at_start = tok.get('ner_at_start', False)
            next_cap = tok.get('ner_next_cap', None)
            if self._is_org_blacklisted(
                atom, original=orig, check_pos=True,
                at_sentence_start=at_start,
                next_is_capitalized=next_cap,
            ):
                gtype = 'concept'
            if self._compound_has_ner_blacklisted(atom):
                gtype = 'concept'
            conditions.append(Term('fact', [Term(atom), Term(gtype)]))

        return self._dedup(conditions, lang='ru')

    def _detect_ru_ner_spans(
        self, text: str,
    ) -> List[Tuple[int, int, str, Optional[str], str]]:
        nlp = self._spacy_ru if self.use_spacy else None
        if nlp is not None:
            try:
                doc = nlp(text)
                spans: List[Tuple[int, int, str, Optional[str], str]] = []
                for ent in doc.ents:
                    if ent.label_ in ('PER', 'PERSON', 'ORG', 'LOC', 'GPE',
                                       'MISC', 'FAC', 'PRODUCT'):
                        atom = "_".join(ent.text.lower().split())
                        gtype = _NER_TO_GRAPH_TYPE.get(ent.label_)
                        spans.append((
                            ent.start_char, ent.end_char,
                            atom, gtype, ent.text,
                        ))
                if spans:
                    return spans
            except Exception as e:
                if self.debug:
                    print(f"[TextToProlog] RU spaCy error: {e}")
        spans = []
        pattern = re.compile(
            r'([А-ЯЁA-Z][а-яёa-zA-Z]+(?:\s+[А-ЯЁA-Z][а-яёa-zA-Z]+)+)'
        )
        for m in pattern.finditer(text):
            atom = "_".join(m.group(1).lower().split())
            spans.append((m.start(), m.end(), atom, None, m.group(1)))
        return spans

    def _build_ru_tokens(self, text: str, words: List[str]) -> List[Dict[str, Any]]:
        text_lower = text.lower()
        positions = []
        pos = 0
        for w in words:
            idx = text_lower.find(w, pos)
            if idx < 0:
                idx = pos
            positions.append((idx, idx + len(w)))
            pos = idx + len(w)

        ner_spans = self._detect_ru_ner_spans(text)

        ner_at_start: Dict[int, bool] = {}
        ner_next_cap: Dict[int, Optional[bool]] = {}
        for si, span_t in enumerate(ner_spans):
            ss = span_t[0]
            se = span_t[1]
            prefix = text[:ss]
            ner_at_start[si] = not re.search(r'[а-яёА-ЯЁa-zA-Z]', prefix)
            j = se
            while j < len(text) and not text[j].isalpha():
                j += 1
            if j < len(text):
                ner_next_cap[si] = text[j].isupper()
            else:
                ner_next_cap[si] = False

        word_to_span = {}
        for i, (ws, we) in enumerate(positions):
            for si, span_t in enumerate(ner_spans):
                ss, se = span_t[0], span_t[1]
                if ws >= ss and we <= se:
                    word_to_span[i] = si
                    break

        span_first = {}
        for i in range(len(words)):
            si = word_to_span.get(i)
            if si is not None and si not in span_first:
                span_first[si] = i

        tokens = []
        for i, w in enumerate(words):
            try:
                parses_all = self._morph_ru.parse(w) if w else []
            except Exception:
                parses_all = []
            parse = None
            for p in parses_all:
                if hasattr(p, 'is_known') and p.is_known:
                    parse = p
                    break
            if parse is None and parses_all:
                parse = parses_all[0]
            norm = (parse.normal_form if parse and parse.normal_form else w)
            tok = {
                'word': w, 'parse': parse, 'norm': norm,
                'is_ner': False, 'ner_atom': None, 'ner_type': None,
                'ner_orig': None, 'ner_at_start': False, 'ner_next_cap': None,
                'is_span_tail': False,
            }
            si = word_to_span.get(i)
            if si is not None:
                span_t = ner_spans[si]
                atom = span_t[2]
                gtype = span_t[3]
                orig = span_t[4] if len(span_t) > 4 else atom
                if i == span_first[si]:
                    tok['is_ner'] = True
                    tok['ner_atom'] = atom
                    tok['ner_type'] = gtype
                    tok['ner_orig'] = orig
                    tok['ner_at_start'] = ner_at_start.get(si, False)
                    tok['ner_next_cap'] = ner_next_cap.get(si, None)
                    tok['norm'] = atom
                else:
                    tok['is_span_tail'] = True
                    tok['norm'] = atom
            tokens.append(tok)
        return tokens

    # ==================================================================
    # EN — spaCy и fallback
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
        token_to_span = {}
        span_entities = []
        _BAD_SPAN_POS = {'VERB', 'AUX'}
        for ent in doc.ents:
            if ent.label_ not in ('PERSON', 'ORG', 'GPE', 'LOC', 'MISC',
                                   'PRODUCT', 'FAC'):
                continue
            if any(tok.pos_ in _BAD_SPAN_POS for tok in ent):
                continue
            span_entities.append(ent)
            for i in range(ent.start, ent.end):
                token_to_span[i] = ent
        conditions = []
        used_tokens = set()

        def span_or_token(tok) -> str:
            if tok.i in token_to_span:
                ent = token_to_span[tok.i]
                for j in range(ent.start, ent.end):
                    used_tokens.add(j)
                return "_".join(ent.text.lower().split())
            compound_indices = [
                c.i for c in tok.children
                if c.dep_ == 'compound' and c.i < tok.i and c.i not in used_tokens
            ]
            if compound_indices:
                compound_indices.sort()
                parts = [doc[i].text.lower() for i in compound_indices]
                parts.append(tok.text.lower())
                for i in compound_indices:
                    used_tokens.add(i)
                used_tokens.add(tok.i)
                return "_".join(parts)
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
            label = "_".join(ent.text.lower().split())
            if label in _STOP_WORDS_EN:
                continue
            gtype = _NER_TO_GRAPH_TYPE.get(ent.label_)
            if gtype is not None:
                conditions.append(Term('fact', [Term(label), Term(gtype)]))
            elif not all(i in used_tokens for i in range(ent.start, ent.end)):
                conditions.append(Term('fact', [Term(label)]))
            for i in range(ent.start, ent.end):
                used_tokens.add(i)

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
        tokens = re.findall(r"[A-Za-z][A-Za-z'\-]*", text)
        if not tokens:
            return []
        lowered = [t.lower() for t in tokens]
        n = len(tokens)

        _span_first = {}
        _span_tail = set()
        i = 0
        while i < n:
            if (tokens[i][:1].isupper()
                    and lowered[i] not in _STOP_WORDS_EN
                    and lowered[i] not in _MODAL_VERBS_EN):
                j = i + 1
                while (j < n
                       and tokens[j][:1].isupper()
                       and lowered[j] not in _STOP_WORDS_EN):
                    j += 1
                if j - i >= 2:
                    atom = "_".join(lowered[i:j])
                    _span_first[i] = (j, atom)
                    for k in range(i + 1, j):
                        _span_tail.add(k)
                    i = j
                    continue
            i += 1

        def _lemma(idx: int) -> str:
            if idx in _span_first:
                return _span_first[idx][1]
            return _en_lemmatize_naive(lowered[idx])

        conditions = []
        used = set()
        last_subject = None

        for i, t in enumerate(lowered):
            if i in used or i in _span_tail:
                continue
            if t in _STOP_WORDS_EN:
                continue
            lemma = _en_lemmatize_naive(t)
            is_verb = (
                t in _EN_COMMON_VERBS
                or lemma in _EN_COMMON_VERBS
                or any(t.endswith(suf) for suf in _EN_VERB_SUFFIXES)
                or t in _MODAL_VERBS_EN
            )
            if not is_verb or t in _MODAL_VERBS_EN:
                continue
            subj = None
            for j in range(i - 1, -1, -1):
                if j in used or j in _span_tail:
                    continue
                wj = lowered[j]
                if wj in _STOP_WORDS_EN:
                    continue
                if any(wj.endswith(suf) for suf in _EN_VERB_SUFFIXES):
                    continue
                subj = _lemma(j)
                used.add(j)
                break
            if subj is None:
                subj = last_subject or "i"
            else:
                last_subject = subj
            pred = lemma
            used.add(i)
            obj = None
            for j in range(i + 1, n):
                if j in used or j in _span_tail:
                    continue
                wj = lowered[j]
                if wj in _STOP_WORDS_EN:
                    continue
                if any(wj.endswith(suf) for suf in _EN_VERB_SUFFIXES):
                    continue
                if any(wj.endswith(suf) for suf in _EN_ADJ_SUFFIXES):
                    continue
                obj = _lemma(j)
                used.add(j)
                break
            if obj:
                conditions.append(Term('triplet', [Term(pred), Term(subj), Term(obj)]))
            else:
                conditions.append(Term('triplet', [Term(pred), Term(subj)]))

        for i in range(n - 2):
            if i in used or (i + 1) in used or (i + 2) in used:
                continue
            if i in _span_tail or (i + 1) in _span_tail or (i + 2) in _span_tail:
                continue
            w1, w2, w3 = lowered[i], lowered[i + 1], lowered[i + 2]
            if w2 not in _EN_IS_FORMS:
                continue
            if w1 in _STOP_WORDS_EN or w3 in _STOP_WORDS_EN:
                continue
            if any(w1.endswith(suf) for suf in _EN_VERB_SUFFIXES):
                continue
            if w3 in _EN_COMMON_VERBS or w3 in _MODAL_VERBS_EN:
                continue
            if (any(w3.endswith(suf) for suf in _EN_VERB_SUFFIXES)
                    and not any(w3.endswith(suf) for suf in _EN_ADJ_SUFFIXES)):
                continue
            conditions.append(Term('attr', [
                Term(_lemma(i)),
                Term(_en_lemmatize_naive(w3)),
            ]))
            used.add(i); used.add(i + 1); used.add(i + 2)

        for i, t in enumerate(lowered):
            if i in used or i in _span_tail or t in _STOP_WORDS_EN:
                continue
            if any(t.endswith(suf) for suf in _EN_VERB_SUFFIXES):
                continue
            if i + 1 < n and (i + 1) not in used and (i + 1) not in _span_tail:
                nxt = lowered[i + 1]
                if (any(t.endswith(suf) for suf in _EN_ADJ_SUFFIXES)
                        and nxt not in _STOP_WORDS_EN):
                    conditions.append(Term('attr', [
                        Term(_lemma(i + 1)),
                        Term(_en_lemmatize_naive(t)),
                    ]))
                    used.add(i); used.add(i + 1)

        for i, t in enumerate(lowered):
            if i in used or i in _span_tail or t in _STOP_WORDS_EN:
                continue
            if not any(t.endswith(suf) for suf in _EN_ADJ_SUFFIXES):
                continue
            adj_lemma = _en_lemmatize_naive(t)
            for j in range(i + 1, min(i + 4, n)):
                if j not in used or j in _span_tail:
                    continue
                noun_lemma = _lemma(j)
                if noun_lemma in _STOP_WORDS_EN:
                    continue
                conditions.append(Term('attr', [Term(noun_lemma), Term(adj_lemma)]))
                used.add(i)
                break

        for i, t in enumerate(lowered):
            if i in used or i in _span_tail or t in _STOP_WORDS_EN:
                continue
            if any(t.endswith(suf) for suf in _EN_VERB_SUFFIXES):
                continue
            conditions.append(Term('fact', [Term(_en_lemmatize_naive(t))]))
            used.add(i)
        return self._dedup(conditions, lang='en')

    def _extract_fallback(self, text: str, lang: str) -> List[Term]:
        if lang == 'en':
            return self._extract_conditions_en_fallback(text)
        words = re.findall(r'[a-zA-Zа-яё]+', text.lower())
        result = []
        seen = set()
        for w in words:
            if w in _STOP_WORDS_RU or w in seen:
                continue
            if self._is_generic_adj(w):
                continue
            if self._is_noise_atom(w):
                continue
            seen.add(w)
            result.append(Term('fact', [Term(w)]))
        return result

    # ==================================================================
    # Определения
    # ==================================================================
    _DEFINITION_PATTERNS = (
        (re.compile(r'^(.+?)\s+(?:—|-|–)\s+(?:это|есть)\s+(.+)$'), 1, 2),
        (re.compile(r'^(.+?)\s+(?:это|есть)\s+(.+)$'), 1, 2),
        (re.compile(r'^(.+?)\s*:\s*(.+)$'), 1, 2),
        (re.compile(r'^(.+?)\s+(?:—|-|–)\s+(.+)$'), 1, 2),
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
    # Граф — факты и запросы
    # ==================================================================
    def _to_graph_program(self, conditions: List[Term]) -> str:
        lines = []
        for c in conditions:
            if c.functor == 'triplet' and len(c.arguments) == 3:
                pred = self._atom(c.arguments[0])
                subj = self._atom(c.arguments[1])
                obj = self._atom(c.arguments[2])
                if (self._is_attr_label(subj)
                        or self._is_attr_label(obj)
                        or self._is_attr_label(pred)):
                    continue
                lines.append(f"edge('{subj}', '{obj}', '{pred}').")
            elif c.functor == 'triplet' and len(c.arguments) == 2:
                pred = self._atom(c.arguments[0])
                subj = self._atom(c.arguments[1])
                if self._is_attr_label(subj) or self._is_attr_label(pred):
                    continue
                lines.append(f"edge('{subj}', _, '{pred}').")
            elif c.functor == 'attr' and len(c.arguments) == 2:
                name = self._atom(c.arguments[0])
                value = self._atom(c.arguments[1])
                lines.append(f"attribute('{name}', '{value}', 'true').")
            elif c.functor == 'attr' and len(c.arguments) == 3:
                name = self._atom(c.arguments[0])
                key = self._atom(c.arguments[1])
                value = self._atom(c.arguments[2])
                lines.append(f"attribute('{name}', '{key}', '{value}').")
            elif c.functor == 'fact' and len(c.arguments) == 1:
                w = self._atom(c.arguments[0])
                lines.append(f"node('{w}', _, concept).")
            elif c.functor == 'fact' and len(c.arguments) == 2:
                w = self._atom(c.arguments[0])
                t = self._atom(c.arguments[1])
                lines.append(f"node('{w}', _, {t}).")
            elif c.functor == 'alias' and len(c.arguments) == 2:
                a = self._atom(c.arguments[0])
                b = self._atom(c.arguments[1])
                lines.append(f"alias('{a}', '{b}').")
        return "\n".join(lines) + "\n" if lines else ""

    def _to_graph_query(self, terms: List[Term]) -> str:
        parts: List[str] = []
        for c in terms:
            if c.functor == '\\+' and len(c.arguments) == 1:
                inner = self._to_graph_query([c.arguments[0]])
                parts.append(f"\\+ ({inner})")
            elif c.functor == 'triplet' and len(c.arguments) == 3:
                pred = self._atom_for_graph(c.arguments[0])
                subj = self._atom_for_graph(c.arguments[1])
                obj = self._atom_for_graph(c.arguments[2])
                parts.append(f"edge({subj}, {obj}, {pred})")
            elif c.functor == 'triplet' and len(c.arguments) == 2:
                pred = self._atom_for_graph(c.arguments[0])
                subj = self._atom_for_graph(c.arguments[1])
                parts.append(f"edge({subj}, _, {pred})")
            elif c.functor == 'attr' and len(c.arguments) == 2:
                name = self._atom_for_graph(c.arguments[0])
                value = self._atom_for_graph(c.arguments[1])
                parts.append(f"attribute({name}, {value}, 'true')")
            elif c.functor == 'attr' and len(c.arguments) == 3:
                name = self._atom_for_graph(c.arguments[0])
                key = self._atom_for_graph(c.arguments[1])
                val_t = c.arguments[2]
                if isinstance(val_t, Variable):
                    parts.append(f"attribute({name}, {key}, {val_t.name})")
                else:
                    parts.append(
                        f"attribute({name}, {key}, {self._atom(val_t)})"
                    )
            elif c.functor == 'fact' and len(c.arguments) == 1:
                w = self._atom_for_graph(c.arguments[0])
                parts.append(f"node({w}, _, concept)")
            elif c.functor == 'fact' and len(c.arguments) == 2:
                w = self._atom_for_graph(c.arguments[0])
                t_term = c.arguments[1]
                if isinstance(t_term, Variable):
                    parts.append(f"node({w}, [], {t_term.name})")
                else:
                    parts.append(f"node({w}, _, {self._atom(t_term)})")
        return ", ".join(parts)

    def _atom_for_graph(self, term) -> str:
        if isinstance(term, Variable):
            return term.name
        if isinstance(term, Term):
            if term.arguments:
                return self._atom(term)
            return f"'{term.functor}'"
        return f"'{term}'"

    def _resolve_lang(self, text: str) -> str:
        if self.default_lang in ('ru', 'en'):
            return self.default_lang
        return detect_lang(text)

    def _dedup(self, conditions: List[Term], lang: str) -> List[Term]:
        if self.use_pymorphy and self._morph_ru is not None:
            def _lemmatize_term(t: Term) -> Term:
                if not t.arguments:
                    return t
                changed = False
                new_args: List[Any] = []
                for a in t.arguments:
                    if isinstance(a, Variable):
                        new_args.append(a)
                    elif isinstance(a, Term) and not a.arguments:
                        w = self._atom(a)
                        wf = self._lemmatize_noun(w)
                        if wf != w:
                            new_args.append(Term(wf))
                            changed = True
                        else:
                            new_args.append(a)
                    else:
                        new_args.append(a)
                return Term(t.functor, new_args) if changed else t

            new_conds: List[Term] = []
            for c in conditions:
                if c.functor in ('fact', 'triplet', 'attr'):
                    new_conds.append(_lemmatize_term(c))
                else:
                    new_conds.append(c)
            conditions = new_conds

        seen: Set[str] = set()
        unique: List[Term] = []
        stop_words = _STOP_WORDS_EN if lang == 'en' else _STOP_WORDS_RU
        adj_stop = _ADJ_STOP_WORDS_EN if lang == 'en' else _ADJ_STOP_WORDS_RU

        in_relation: Set[str] = set()
        typed_atoms: Set[str] = set()
        aliased: Set[str] = set()

        for c in conditions:
            if c.functor == 'triplet' and len(c.arguments) >= 2:
                in_relation.add(self._atom(c.arguments[1]))
                if len(c.arguments) == 3:
                    in_relation.add(self._atom(c.arguments[2]))
            elif c.functor == 'attr' and len(c.arguments) >= 2:
                in_relation.add(self._atom(c.arguments[0]))
            elif c.functor == 'fact' and len(c.arguments) == 2:
                typed_atoms.add(self._atom(c.arguments[0]))
            elif c.functor == 'alias' and len(c.arguments) == 2:
                aliased.add(self._atom(c.arguments[0]))

        for c in conditions:
            s = self._term_key(c)
            if s in seen:
                continue
            seen.add(s)

            if c.functor == 'triplet' and len(c.arguments) >= 2:
                _skip = False
                _skip_reason = ''
                for _i in range(1, len(c.arguments)):
                    _arg = c.arguments[_i]
                    if isinstance(_arg, Variable):
                        continue
                    _name = self._atom(_arg)
                    if _name in _WH_LEMMAS_RU:
                        continue
                    if self._is_generic_adj(_name):
                        _skip = True
                        _skip_reason = f'generic_adj: {_name}'
                        break
                    if '_' in _name and self._compound_has_ner_blacklisted(_name):
                        _skip = True
                        _skip_reason = f'compound_ner_blacklisted: {_name}'
                        break
                if _skip:
                    self._log_filtered(self._term_desc(c), _skip_reason)
                    continue

            if c.functor == 'attr' and c.arguments:
                _name = self._atom(c.arguments[0])
                if self._is_generic_adj(_name):
                    self._log_filtered(
                        self._term_desc(c),
                        f'attr name generic_adj: {_name}')
                    continue
                if '_' in _name and self._compound_has_ner_blacklisted(_name):
                    self._log_filtered(
                        self._term_desc(c),
                        f'attr name compound_ner_blacklisted: {_name}')
                    continue
                if len(c.arguments) == 2:
                    _val_arg = c.arguments[1]
                    if not isinstance(_val_arg, Variable):
                        _val = self._atom(_val_arg)
                        if self._is_attr_adj_noise(_val):
                            self._log_filtered(
                                self._term_desc(c),
                                f'attr value noise: {_val}')
                            continue

            if c.functor == 'fact' and c.arguments:
                w = self._atom(c.arguments[0])
                if w in stop_words or w in adj_stop:
                    continue
                if self._is_generic_adj(w):
                    self._log_filtered(
                        self._term_desc(c), f'generic_adj: {w}')
                    continue
                if self._is_noise_atom(w):
                    self._log_filtered(
                        self._term_desc(c), f'noise_atom: {w}')
                    continue
                if '_' in w and self._compound_has_ner_blacklisted(w):
                    self._log_filtered(
                        self._term_desc(c),
                        f'compound_ner_blacklisted: {w}')
                    continue
                if len(c.arguments) == 1 and (w in in_relation or w in typed_atoms):
                    continue
                if len(c.arguments) == 1 and w in aliased:
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
        args = []
        current = []
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
        elements = []
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
    text: str, mode: str = "condition", predicate: str = "user_condition",
    **kwargs: Any,
) -> str:
    return TextToProlog(**kwargs).convert(text, mode=mode, predicate=predicate)


def parse_text(text: str, **kwargs: Any) -> Tuple[str, str]:
    t2p_kwargs = {k: v for k, v in kwargs.items()
                  if k in ('use_pymorphy', 'use_spacy', 'use_natasha',
                           'debug', 'default_lang')}
    parse_kwargs = {k: v for k, v in kwargs.items()
                    if k in ('lang', 'facts_mode', 'query_mode', 'predicate',
                             'semantic', 'semantic_threshold',
                             'link_components', 'strict',
                             'log_filtered', 'facts_from_questions')}
    t2p = TextToProlog(**t2p_kwargs)
    return t2p.parse(text, **parse_kwargs)