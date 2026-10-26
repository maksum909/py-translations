from __future__ import annotations

from typing import Any

from django.db import models

from py_translations.exceptions import UnloadedTranslation
from py_translations.languages import validate_language

READY = "_py_translation_ready"
CACHE = "_py_translation_cache"
DIRTY = "_py_translation_dirty"
DELETED = "_py_translation_deleted"


def field_names(model: type) -> list[str]:
    return list(getattr(model, "_py_translations_field_names", ()))


def uses_table(model: type) -> bool:
    return getattr(model, "_py_translation_backend", "json") == "table"


def json_field_names(model: type) -> list[str]:
    if uses_table(model):
        return []
    return field_names(model)


def get_translated_field(model: type, name: str) -> Any | None:
    if name not in getattr(model, "_py_translations_field_names", ()):
        return None
    attr = getattr(model, name, None)
    if hasattr(attr, "raw_map"):
        return attr
    wrapped = getattr(attr, "field", None)
    if hasattr(wrapped, "raw_map"):
        return wrapped
    try:
        field = model._meta.get_field(name)  # type: ignore[attr-defined]
    except Exception:
        return None
    if hasattr(field, "raw_map"):
        return field
    return None


def require_translated_field(model: type, name: str) -> Any:
    field = get_translated_field(model, name)
    if field is None:
        raise TypeError(f"{getattr(model, '__name__', model)}.{name} is not a translated field.")
    return field


def init_cache(instance: models.Model) -> None:
    setattr(instance, CACHE, {})
    setattr(instance, DIRTY, set())
    setattr(instance, DELETED, set())
    setattr(instance, READY, True)


def hydrate(instance: models.Model) -> bool:
    if getattr(instance, READY, False):
        return True
    prefetched = getattr(instance, "_prefetched_objects_cache", {}).get("translations")
    if prefetched is None:
        return False
    loaded: dict[str, dict[str, Any]] = {}
    names = field_names(type(instance))
    for row in prefetched:
        loaded[row.language_code] = {name: getattr(row, name) for name in names}
    setattr(instance, CACHE, loaded)
    setattr(instance, DIRTY, set())
    setattr(instance, DELETED, set())
    setattr(instance, READY, True)
    return True


def ensure_cache(instance: models.Model, *, load: bool) -> None:
    if hydrate(instance):
        return
    if load and instance.pk and not instance._state.adding:
        instance.load_translations()  # type: ignore[attr-defined]
        return
    if instance._state.adding or not instance.pk:
        init_cache(instance)
        return
    raise UnloadedTranslation(
        f"{type(instance).__name__} has no translation cache. "
        "Load it with the default manager, .with_translations(), or load_translations()."
    )


def prepare_instance(instance: models.Model, *, language: str | None, pinned: bool) -> None:
    if pinned and language:
        instance._translation_language = language  # type: ignore[attr-defined]
    if uses_table(type(instance)):
        hydrate(instance)


def persist_translations(instance: models.Model, *, using: str | None) -> None:
    if not getattr(instance, READY, False):
        return
    model = type(instance)._py_translation_model  # type: ignore[attr-defined]
    db = using or instance._state.db
    manager = model.objects.using(db) if db else model.objects
    deleted = set(getattr(instance, DELETED, ()))
    if deleted:
        manager.filter(master=instance, language_code__in=deleted).delete()
        getattr(instance, DELETED).clear()
    dirty = set(getattr(instance, DIRTY, ()))
    if not dirty:
        return
    names = field_names(type(instance))
    cache: dict[str, dict[str, Any]] = getattr(instance, CACHE)
    rows = []
    for language in dirty:
        data = cache.get(language, {})
        rows.append(
            model(
                master=instance,
                language_code=language,
                **{name: data.get(name) for name in names},
            )
        )
    manager.bulk_create(
        rows,
        update_conflicts=True,
        unique_fields=["master", "language_code"],
        update_fields=names,
    )
    getattr(instance, DIRTY).clear()


def mark_language(instance: models.Model, language: str) -> dict[str, Any]:
    validate_language(language)
    ensure_cache(instance, load=True)
    bucket = getattr(instance, CACHE).setdefault(language, {})
    getattr(instance, DIRTY).add(language)
    getattr(instance, DELETED).discard(language)
    return bucket
