"""noise.py — универсальная проверка служебных слов для графа знаний.

Основной механизм — POS-теги через pymorphy3 (RU) / spaCy (EN).
Резерв — маленький курированный лексикон субстантивированных
указательных слов ("данные", "следующее", ...), которые POS не отличит
от обычных существительных.

Расширяется через файлы noise_ru.txt / noise_en.txt в каталоге модуля
(одно слово на строку, # комментарии игнорируются).

v5.11.2 (fix A + B):
    * Fix A: `_RU_SERVICE_POS` дополнен `INFN` — инфинитивы
      (`расположить`, `планировать`, `заключить`, ...) больше не
      эмитятся как `attribute(..., 'расположить', 'true')`.
    * Fix B: `is_common_noun_ner(..., next_is_capitalized=None)`.
      Для capitalized single-token NOUN без proper-тегов:
        - `at_sentence_start=True`       → common;
        - `next_is_capitalized=False`    → common (напр. «Соглашение о»);
        - `next_is_capitalized=True`     → proper (напр. «Правительство
          Российской»);
        - `next_is_capitalized=None`     → proper (безопасный дефолт).
      Позволяет отсеять «Соглашение»/«Стороны»/«Заявление» в середине
      предложения, не теряя «Правительство Российской Федерации».

Публичный API:
    is_service_word(w, lang='ru') -> bool
    is_common_noun_ner(surface, lang='ru',
                       at_sentence_start=False,
                       next_is_capitalized=None) -> bool
    reload_noise_words() -> None
"""
from __future__ import annotations

import os
from typing import Optional


# ---------------------------------------------------------------- pymorphy3
try:
    from pymorphy3 import MorphAnalyzer  # type: ignore
    _PYMORPH = MorphAnalyzer()
except Exception:
    _PYMORPH = None


# ---------------------------------------------------------------- spaCy (EN)
_SPACY_EN = None
_SPACY_LOADED = False


def _get_spacy_en():
    global _SPACY_EN, _SPACY_LOADED
    if _SPACY_LOADED:
        return _SPACY_EN
    _SPACY_LOADED = True
    try:
        import spacy
        _SPACY_EN = spacy.load("en_core_web_sm")
    except Exception:
        _SPACY_EN = None
    return _SPACY_EN


# ---------------------------------------------------------------- POS-классы
# v5.11.2 (fix A): INFN — инфинитивы. Они не могут быть узлами графа.
_RU_SERVICE_POS = frozenset({
    'ADJF', 'ADJS', 'COMP',
    'PRTF', 'PRTS', 'GRND',
    'ADVB', 'NPRO',
    'PREP', 'CONJ', 'PRCL', 'INTJ', 'NUMR',
    'INFN',
})

_EN_SERVICE_POS = frozenset({
    'ADJ', 'ADV', 'ADP', 'AUX', 'CCONJ', 'SCONJ',
    'DET', 'INTJ', 'NUM', 'PART', 'PRON',
    'PUNCT', 'SYM', 'SPACE', 'X',
})


# ---------------------------------------------------------------- курированный резерв
_SUBST_RU: frozenset = frozenset({
    'данные', 'данных', 'данным', 'данными',
    'данное', 'данного', 'данному',
    'указанное', 'указанного', 'указанному',
    'указанные', 'указанных', 'указанным', 'указанными',
    'перечисленное', 'перечисленного', 'перечисленному',
    'перечисленные', 'перечисленных',
    'настоящее', 'настоящего', 'настоящему', 'настоящим',
    'вышеуказанное', 'вышеуказанного',
    'нижеследующее', 'нижеследующего',
    'вышеизложенное', 'нижеизложенное',
    'приведенное', 'приведённое',
    'изложенное', 'изложенного',
    'поименованное', 'поименованного',
})

_SUBST_EN: frozenset = frozenset({
    'aforementioned', 'aforesaid', 'foregoing',
    'following', 'above', 'below', 'said',
})


# ---------------------------------------------------------------- расширение
_HERE = os.path.dirname(os.path.abspath(__file__))
_NOISE_FILES = {
    'ru': os.path.join(_HERE, 'noise_ru.txt'),
    'en': os.path.join(_HERE, 'noise_en.txt'),
}
_EXTRA_NOISE: dict = {'ru': set(), 'en': set()}
_EXTRA_LOADED = False


def reload_noise_words() -> None:
    """Перечитать noise_ru.txt / noise_en.txt (одно слово на строку)."""
    global _EXTRA_LOADED
    _EXTRA_NOISE['ru'].clear()
    _EXTRA_NOISE['en'].clear()
    for lang, path in _NOISE_FILES.items():
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding='utf-8') as f:
                for line in f:
                    w = line.split('#', 1)[0].strip().lower()
                    if w:
                        _EXTRA_NOISE[lang].add(w)
        except Exception:
            pass
    _EXTRA_LOADED = True


def _ensure_extra_loaded() -> None:
    if not _EXTRA_LOADED:
        reload_noise_words()


# ---------------------------------------------------------------- API
def is_service_word(w: str, lang: str = 'ru') -> bool:
    """True, если w — служебное слово (прилагательное, причастие,
    инфинитив, местоимение, предлог, союз, частица, числительное,
    субстантивированное указательное)."""
    if not w:
        return True
    wl = w.strip().lower()
    if not wl:
        return True

    _ensure_extra_loaded()
    if wl in _EXTRA_NOISE.get(lang, set()):
        return True

    if lang == 'ru':
        if wl in _SUBST_RU:
            return True
        if _PYMORPH is not None:
            try:
                parses = _PYMORPH.parse(wl)
                if parses:
                    pos = parses[0].tag.POS
                    if pos in _RU_SERVICE_POS:
                        return True
            except Exception:
                pass
        return False

    if lang == 'en':
        if wl in _SUBST_EN:
            return True
        nlp = _get_spacy_en()
        if nlp is not None:
            try:
                doc = nlp(wl)
                if doc and len(doc) == 1:
                    if doc[0].pos_ in _EN_SERVICE_POS:
                        return True
            except Exception:
                pass
        return False

    return False


def is_common_noun_ner(
    surface: str,
    lang: str = 'ru',
    at_sentence_start: bool = False,
    next_is_capitalized: Optional[bool] = None,
) -> bool:
    """True, если NER ошибочно присвоил ORG/LOC обычному нарицательному
    существительному.

    v5.11.2 (fix B): для capitalized single-token NOUN без proper-тегов
    использует `next_is_capitalized` как дополнительный сигнал:
    capitalized + lowercase next → common (напр. «Соглашение о …»).
    capitalized + capitalized next → proper (напр. «Правительство
    Российской»).
    """
    if not surface:
        return False

    # Multi-word спаны — почти всегда proper noun. Не фильтруем.
    if ('_' in surface.strip()) or (' ' in surface.strip()):
        return False

    first_raw = surface.strip()
    if not first_raw:
        return False
    first_raw = first_raw.strip('.,;:!?\'"«»()–—/\\[]{}<>')
    if not first_raw:
        return False

    first = first_raw.lower()
    is_capitalized = first_raw[:1].isupper()

    if lang == 'ru' and _PYMORPH is not None:
        try:
            parses = _PYMORPH.parse(first)
            if parses:
                best = parses[0]
                if best.tag.POS == 'NOUN':
                    tag_str = str(best.tag)
                    has_proper = any(
                        t in tag_str
                        for t in ('Name', 'Surn', 'Patr', 'Geox', 'Orgn')
                    )
                    if has_proper:
                        return False
                    # v5.11.2: lowercase NOUN = common.
                    if not is_capitalized:
                        return True
                    # Capitalized single-token NOUN без proper-тегов.
                    if at_sentence_start:
                        return True
                    if next_is_capitalized is False:
                        return True  # «Соглашение о» — common
                    if next_is_capitalized is True:
                        return False  # «Правительство Российской» — proper
                    return False  # unknown — proper (safe default)
        except Exception:
            pass

    if lang == 'en':
        nlp = _get_spacy_en()
        if nlp is not None:
            try:
                doc = nlp(first)
                if doc and len(doc) == 1:
                    pos = doc[0].pos_
                    if pos == 'PROPN':
                        return False
                    if pos in ('NOUN', 'VERB', 'ADJ'):
                        if not is_capitalized:
                            return True
                        if at_sentence_start:
                            return True
                        if next_is_capitalized is False:
                            return True
                        if next_is_capitalized is True:
                            return False
                        return False
            except Exception:
                pass

    return False