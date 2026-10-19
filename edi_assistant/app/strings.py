"""UI string loader: `S.KEY` / `tr("KEY")` resolve against the module chosen by config ui.language ('en' | 'vi').

The language is read lazily from the saved config on first use (so a restart is needed after changing it);
`set_language()` overrides it explicitly (used by the app bootstrap and tests).
"""
from __future__ import annotations

import importlib
from types import ModuleType

DEFAULT_LANGUAGE = "en"
LANGUAGES = ("en", "vi")
_MODULES = {"en": "strings_en", "vi": "strings_vi"}

_lang: str | None = None
_mod: ModuleType | None = None


def normalize(lang: str | None) -> str:
    lang = (lang or "").strip().lower()
    return lang if lang in LANGUAGES else DEFAULT_LANGUAGE


def set_language(lang: str | None) -> str:
    global _lang, _mod
    _lang = normalize(lang)
    _mod = importlib.import_module(f"{__package__}.{_MODULES[_lang]}")
    return _lang


def language() -> str:
    if _lang is None:
        _resolve()
    return _lang or DEFAULT_LANGUAGE


def _resolve() -> ModuleType:
    if _mod is not None:
        return _mod
    try:
        from edi_assistant.core.config import load_config
        lang = load_config().ui.language
    except Exception:
        lang = DEFAULT_LANGUAGE
    set_language(lang)
    return _mod  # type: ignore[return-value]


class _Strings:
    """Attribute proxy so existing `S.NAME` usages keep working with a runtime-selected module."""

    def __getattr__(self, name: str):
        return getattr(_resolve(), name)


S = _Strings()


def tr(key: str, **fmt):
    val = getattr(_resolve(), key)
    return val.format(**fmt) if fmt and isinstance(val, str) else val
