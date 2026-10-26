from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

DEFAULTS: dict[str, Any] = {
    "BACKEND": "json",
    "DEFAULT_LANGUAGE": None,
    "LANGUAGES": None,
    "FALLBACKS": {},
}


def get_config() -> dict[str, Any]:
    user = getattr(settings, "PY_TRANSLATIONS", {})
    if not isinstance(user, dict):
        raise ImproperlyConfigured("PY_TRANSLATIONS must be a dict.")
    return {**DEFAULTS, **user}


def get_default_language() -> str:
    configured = get_config().get("DEFAULT_LANGUAGE")
    if configured:
        return str(configured)
    return settings.LANGUAGE_CODE


def configured_languages() -> list[str]:
    configured = get_config().get("LANGUAGES")
    if not configured:
        return [code for code, _name in settings.LANGUAGES]
    languages: list[str] = []
    for item in configured:
        if isinstance(item, str):
            languages.append(item)
        else:
            languages.append(item[0])
    return languages


def language_label(code: str) -> str:
    names = dict(settings.LANGUAGES)
    name = names.get(code)
    if name:
        return f"{name} ({code})"
    return code
