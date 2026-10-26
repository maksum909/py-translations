from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from py_translations.conf import get_config


def resolve_backend(model: type) -> str:
    for klass in model.__mro__:
        conf = klass.__dict__.get("Translations")
        if conf is not None and hasattr(conf, "backend"):
            backend = conf.backend
            if backend not in {"json", "table"}:
                raise ValueError(
                    f"{getattr(model, '__name__', model)} Translations.backend must be "
                    f"'json' or 'table', got {backend!r}."
                )
            return backend
    if not settings.configured:
        return "json"
    backend = get_config()["BACKEND"]
    if backend not in {"json", "table"}:
        raise ImproperlyConfigured("PY_TRANSLATIONS['BACKEND'] must be 'json' or 'table'.")
    return backend
