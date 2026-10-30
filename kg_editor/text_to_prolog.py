# kg-editor/text_to_prolog.py (shim)
"""Тонкая обёртка для обратной совместимости."""
from nl2prolog import (  # noqa: F401
    TextToProlog,
    Term,
    Variable,
    detect_lang,
    extract_conditions,
    parse_text,
    text_to_prolog,
    runtime_info,
    __version__,
)

__all__ = [
    "TextToProlog", "Term", "Variable", "detect_lang",
    "extract_conditions", "parse_text", "text_to_prolog",
    "runtime_info", "__version__",
]