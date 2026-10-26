from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.utils.translation import get_language

from py_translations.conf import get_config, get_default_language

if TYPE_CHECKING:
    from py_translations.fields import TranslatedField


def validate_language(language: str) -> str:
    if not isinstance(language, str) or not language or "__" in language or len(language) > 32:
        raise ValueError(
            f"Invalid language code {language!r}. Use a code of 1..32 characters without '__'."
        )
    return language


def get_active_language(instance: object | None = None) -> str:
    if instance is not None:
        pinned = getattr(instance, "_translation_language", None)
        if pinned:
            return str(pinned)
    current = get_language()
    if current:
        return current
    return get_default_language()


def fallback_chain(instance: object, field: TranslatedField[Any]) -> list[str]:
    active = get_active_language(instance)
    chain = [active]
    for language in _extra_fallbacks(instance, field, active):
        if language not in chain:
            chain.append(language)
    return chain


def prefetch_languages(model: type, active: str | None) -> list[str] | None:
    """Languages a table-backend prefetch should load.

    ``None`` means every language. A pinned language still loads its fallbacks,
    because attribute access walks that chain in Python.
    """
    if active is None:
        return None
    languages = [active]
    for name in getattr(model, "_py_translations_field_names", ()):
        field = getattr(model, name)
        for language in _extra_fallbacks_for_model(model, field, active):
            if language not in languages:
                languages.append(language)
    return languages


def _extra_fallbacks(instance: object, field: TranslatedField[Any], active: str) -> list[str]:
    if field.fallback is not None:
        return list(field.fallback)
    return _extra_fallbacks_for_model(type(instance), field, active)


def _extra_fallbacks_for_model(model: type, field: TranslatedField[Any], active: str) -> list[str]:
    if field.fallback is not None:
        return list(field.fallback)
    for klass in model.__mro__:
        conf = klass.__dict__.get("Translations")
        if conf is not None and hasattr(conf, "fallbacks"):
            mapping = conf.fallbacks
            if active in mapping:
                return list(mapping[active])
            if "*" in mapping:
                return list(mapping["*"])
            return []
    project = get_config().get("FALLBACKS") or {}
    if active in project:
        return list(project[active])
    if "*" in project:
        return list(project["*"])
    return []
