from __future__ import annotations

from contextlib import contextmanager
from typing import Any, ClassVar

import django
from django.core import checks
from django.db import models, transaction
from django.db.models.base import ModelBase

from py_translations.backends import resolve_backend
from py_translations.languages import validate_language
from py_translations.query import TranslatableManager
from py_translations.storage import (
    CACHE,
    DELETED,
    DIRTY,
    READY,
    ensure_cache,
    field_names,
    init_cache,
    json_field_names,
    persist_translations,
    require_translated_field,
    uses_table,
)


class TranslatableModelBase(ModelBase):
    def __new__(mcs, name, bases, attrs, **kwargs):
        new_class = super().__new__(mcs, name, bases, attrs, **kwargs)
        backend = resolve_backend(new_class)
        new_class._py_translation_backend = backend
        if new_class._meta.abstract:
            return new_class
        if new_class._meta.proxy:
            concrete = new_class._meta.concrete_model
            new_class._py_translation_backend = getattr(
                concrete, "_py_translation_backend", backend
            )
            if hasattr(concrete, "_py_translation_model"):
                new_class._py_translation_model = concrete._py_translation_model
            return new_class
        if backend == "table":
            from py_translations.backends.table import create_translation_model

            create_translation_model(new_class)
        return new_class


class TranslatableModel(models.Model, metaclass=TranslatableModelBase):
    objects: ClassVar[TranslatableManager] = TranslatableManager()
    _py_translations_field_names: ClassVar[list[str]] = []
    _py_translation_backend: ClassVar[str] = "json"

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        translated: dict[str, Any] = {}
        if uses_table(type(self)):
            for name in field_names(type(self)):
                if name in kwargs:
                    translated[name] = kwargs.pop(name)
            init_cache(self)
        super().__init__(*args, **kwargs)
        for name, value in translated.items():
            setattr(self, name, value)

    @classmethod
    def from_db(cls, db, field_names_from_db, values):
        instance = super().from_db(db, field_names_from_db, values)
        # Query construction calls __init__, which arms an empty table cache.
        # Drop that flag so the prefetch result can fill the real rows.
        if uses_table(cls):
            setattr(instance, READY, False)
        return instance

    def save(self, *args, **kwargs):
        if not uses_table(type(self)):
            return super().save(*args, **kwargs)
        using = kwargs.get("using")
        with transaction.atomic(using=using):
            result = super().save(*args, **kwargs)
            persist_translations(self, using=using)
            return result

    def refresh_from_db(self, using=None, fields=None, **kwargs):
        if django.VERSION >= (5, 1):
            super().refresh_from_db(using=using, fields=fields, **kwargs)
        else:
            super().refresh_from_db(using=using, fields=fields)
        if uses_table(type(self)):
            if fields is None:
                setattr(self, READY, False)
                self.load_translations()
            return
        # Django copies columns with getattr(). The descriptor returns one
        # language, so put the stored JSON maps back from a values() query.
        translated = json_field_names(type(self))
        if fields is not None:
            wanted = set(fields)
            translated = [name for name in translated if name in wanted]
        if not translated or self.pk is None:
            return
        db = self._state.db if using is None else using
        source = kwargs.get("from_queryset")
        if source is None:
            manager = type(self)._base_manager
            source = manager.using(db) if db else manager
        elif using is not None:
            source = source.using(using)
        row = source.filter(pk=self.pk).values(*translated).get()
        for name in translated:
            value = row[name]
            self.__dict__[name] = value if isinstance(value, dict) else {}

    def load_translations(self):
        if not uses_table(type(self)):
            return self
        model = type(self)._py_translation_model
        db = self._state.db
        manager = model.objects.using(db) if db else model.objects
        loaded: dict[str, dict[str, Any]] = {}
        names = field_names(type(self))
        for row in manager.filter(master=self):
            loaded[row.language_code] = {name: getattr(row, name) for name in names}
        setattr(self, CACHE, loaded)
        setattr(self, DIRTY, set())
        setattr(self, DELETED, set())
        setattr(self, READY, True)
        return self

    def set_translation(self, language: str, **values: Any):
        validate_language(language)
        known = set(field_names(type(self)))
        unknown = set(values) - known
        if unknown:
            raise TypeError(f"Unknown translated fields: {', '.join(sorted(unknown))}")
        for name, value in values.items():
            require_translated_field(type(self), name).set_language(self, language, value)
        return self

    def get_translation(self, language: str) -> dict[str, Any]:
        validate_language(language)
        result: dict[str, Any] = {}
        for name in field_names(type(self)):
            field = require_translated_field(type(self), name)
            raw = field.raw_map(self)
            if language in raw and raw[language] is not None:
                result[name] = field.inner.to_python(raw[language])
        return result

    def delete_translation(self, language: str) -> None:
        validate_language(language)
        if uses_table(type(self)):
            ensure_cache(self, load=True)
            getattr(self, CACHE).pop(language, None)
            getattr(self, DELETED).add(language)
            getattr(self, DIRTY).discard(language)
            return
        for name in field_names(type(self)):
            require_translated_field(type(self), name).clear_language(self, language)

    def get_available_languages(self) -> list[str]:
        languages: list[str] = []
        for name in field_names(type(self)):
            field = require_translated_field(type(self), name)
            for language, value in field.raw_map(self).items():
                if value is not None and language not in languages:
                    languages.append(language)
        return languages

    def has_translation(self, language: str, field: str | None = None) -> bool:
        data = self.get_translation(language)
        if field is None:
            return bool(data)
        return field in data

    @contextmanager
    def as_language(self, language: str):
        validate_language(language)
        had = hasattr(self, "_translation_language")
        previous: Any = getattr(self, "_translation_language", None)
        self._translation_language = language
        try:
            yield self
        finally:
            if had:
                self._translation_language = previous
            else:
                del self._translation_language

    @classmethod
    def check(cls, **kwargs):
        errors = super().check(**kwargs)
        errors.extend(_inheritance_errors(cls))
        return errors


def _inheritance_errors(cls: type[TranslatableModel]) -> list[checks.Error]:
    if cls._meta.abstract or cls._meta.proxy:
        return []
    errors: list[checks.Error] = []
    for parent in cls._meta.parents:
        if parent is TranslatableModel or not issubclass(parent, TranslatableModel):
            continue
        if not parent._meta.abstract:
            errors.append(
                checks.Error(
                    f"{cls.__name__} multi-table-inherits translations from {parent.__name__}.",
                    hint="Make the parent abstract, or translate fields only on the child.",
                    obj=cls,
                    id="py_translations.E001",
                )
            )
    own = cls.__dict__.get("Translations")
    if own is not None and hasattr(own, "backend"):
        for parent in cls.__mro__[1:]:
            parent_fields = parent.__dict__.get("_py_translations_field_names")
            parent_backend = parent.__dict__.get("_py_translation_backend")
            if parent_fields and parent_backend and parent_backend != own.backend:
                errors.append(
                    checks.Error(
                        (
                            f"{cls.__name__} changes the translation backend "
                            f"declared on {parent.__name__}."
                        ),
                        hint="Pick the backend on the model that declares the translated fields.",
                        obj=cls,
                        id="py_translations.E002",
                    )
                )
                break
    return errors
