from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Generic, TypeVar, overload
from uuid import UUID

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from py_translations.backends import resolve_backend
from py_translations.languages import fallback_chain, get_active_language, validate_language
from py_translations.storage import CACHE, ensure_cache, mark_language

_GT = TypeVar("_GT")

_DISALLOWED = (models.FileField, models.JSONField, models.BinaryField, models.AutoField)


class TranslationDescriptor:
    """Resolves one language. Django 5.1+ wraps fields in DeferredAttribute."""

    def __init__(self, field: TranslatedField[Any]) -> None:
        self.field = field

    def __get__(self, instance: models.Model | None, owner: type[models.Model]) -> Any:
        if instance is None:
            return self.field
        return self.field.resolve_value(instance)

    def __set__(self, instance: models.Model, value: Any) -> None:
        self.field.assign_value(instance, value)


class TranslatedField(models.JSONField, Generic[_GT]):
    """A translated value stored as a language map, read as the inner field's type.

    ``pre_save`` returns the raw map. ``__get__`` resolves one language. Model
    save reads fields through ``pre_save``, so the two paths stay separate.
    """

    @overload
    def __new__(
        cls,
        field: models.CharField,
        *,
        fallback: list[str] | None = ...,
        **kwargs: Any,
    ) -> TranslatedField[str]: ...

    @overload
    def __new__(
        cls,
        field: models.TextField,
        *,
        fallback: list[str] | None = ...,
        **kwargs: Any,
    ) -> TranslatedField[str]: ...

    @overload
    def __new__(
        cls,
        field: models.IntegerField,
        *,
        fallback: list[str] | None = ...,
        **kwargs: Any,
    ) -> TranslatedField[int]: ...

    @overload
    def __new__(
        cls,
        field: models.FloatField,
        *,
        fallback: list[str] | None = ...,
        **kwargs: Any,
    ) -> TranslatedField[float]: ...

    @overload
    def __new__(
        cls,
        field: models.DecimalField,
        *,
        fallback: list[str] | None = ...,
        **kwargs: Any,
    ) -> TranslatedField[Decimal]: ...

    @overload
    def __new__(
        cls,
        field: models.BooleanField,
        *,
        fallback: list[str] | None = ...,
        **kwargs: Any,
    ) -> TranslatedField[bool]: ...

    @overload
    def __new__(
        cls,
        field: models.DateTimeField,
        *,
        fallback: list[str] | None = ...,
        **kwargs: Any,
    ) -> TranslatedField[datetime]: ...

    @overload
    def __new__(
        cls,
        field: models.DateField,
        *,
        fallback: list[str] | None = ...,
        **kwargs: Any,
    ) -> TranslatedField[date]: ...

    @overload
    def __new__(
        cls,
        field: models.TimeField,
        *,
        fallback: list[str] | None = ...,
        **kwargs: Any,
    ) -> TranslatedField[time]: ...

    @overload
    def __new__(
        cls,
        field: models.UUIDField,
        *,
        fallback: list[str] | None = ...,
        **kwargs: Any,
    ) -> TranslatedField[UUID]: ...

    @overload
    def __new__(
        cls,
        field: models.Field[Any, Any],
        *,
        fallback: list[str] | None = ...,
        **kwargs: Any,
    ) -> TranslatedField[Any]: ...

    def __new__(cls, field: models.Field[Any, Any], *args: Any, **kwargs: Any) -> Any:
        return super().__new__(cls)

    def __init__(
        self,
        field: models.Field[Any, Any],
        *,
        fallback: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        self._validate_inner(field)
        self.inner = field.clone()
        self.fallback = list(fallback) if fallback is not None else None
        self.backend = "json"
        kwargs.setdefault("default", dict)
        kwargs.setdefault("blank", False)
        kwargs.setdefault("encoder", DjangoJSONEncoder)
        super().__init__(**kwargs)

    def deconstruct(self):  # type: ignore[override]
        name, path, args, kwargs = super().deconstruct()
        kwargs["field"] = self.inner.clone()
        if self.fallback is not None:
            kwargs["fallback"] = list(self.fallback)
        return name, path, args, kwargs

    def contribute_to_class(
        self, cls: type[models.Model], name: str, private_only: bool = False
    ) -> None:
        self.backend = resolve_backend(cls)
        _register(cls, name)
        if self.backend == "table":
            self.set_attributes_from_name(name)
            self.model = cls
            setattr(cls, name, TranslationDescriptor(self))
            return
        super().contribute_to_class(cls, name, private_only=private_only)
        setattr(cls, self.attname, TranslationDescriptor(self))

    @overload  # type: ignore[override]
    def __get__(self, instance: None, owner: type[models.Model]) -> TranslatedField[_GT]: ...

    @overload
    def __get__(self, instance: models.Model, owner: type[models.Model]) -> _GT: ...

    def __get__(  # type: ignore[override]
        self, instance: models.Model | None, owner: type[models.Model]
    ) -> TranslatedField[_GT] | _GT | None:
        if instance is None:
            return self
        return self.resolve_value(instance)

    def __set__(self, instance: models.Model, value: _GT | dict[str, Any]) -> None:
        self.assign_value(instance, value)

    def resolve_value(self, instance: models.Model) -> Any:
        return self._resolve(instance, self.raw_map(instance))

    def assign_value(self, instance: models.Model, value: Any) -> None:
        if isinstance(value, dict):
            if self.backend == "table":
                for language, item in value.items():
                    self.set_language(instance, str(language), item)
                return
            instance.__dict__[self.attname] = dict(value)
            return
        self.set_language(instance, get_active_language(instance), value)

    def set_language(self, instance: models.Model, language: str, value: Any) -> None:
        validate_language(language)
        if self.backend == "table":
            mark_language(instance, language)[self.name] = value
            return
        raw = self._json_map(instance)
        if value is None:
            raw.pop(language, None)
        else:
            raw[language] = value
        instance.__dict__[self.attname] = raw

    def clear_language(self, instance: models.Model, language: str) -> None:
        validate_language(language)
        if self.backend == "table":
            mark_language(instance, language)[self.name] = None
            return
        raw = self._json_map(instance)
        raw.pop(language, None)
        instance.__dict__[self.attname] = raw

    def raw_map(self, instance: models.Model) -> dict[str, Any]:
        if self.backend == "table":
            ensure_cache(instance, load=False)
            result: dict[str, Any] = {}
            for language, bucket in getattr(instance, CACHE).items():
                if self.name in bucket and bucket[self.name] is not None:
                    result[language] = bucket[self.name]
            return result
        return self._json_map(instance)

    def pre_save(self, model_instance: models.Model, add: bool) -> Any:
        # Model.save() asks the descriptor for a value. Returning the resolved
        # string here would persist that string instead of the language map.
        if self.backend == "table":
            return None
        raw = model_instance.__dict__.get(self.attname)
        if not isinstance(raw, dict):
            return {}
        return raw

    def formfield(self, **kwargs: Any) -> Any:
        defaults = {"required": not self.inner.blank}
        defaults.update(kwargs)
        return self.inner.formfield(**defaults)

    def value_from_object(self, obj: models.Model) -> Any:
        return self.__get__(obj, type(obj))

    def clean(self, value: Any, model_instance: models.Model | None) -> Any:
        if value in self.inner.empty_values and self.inner.blank:
            return value
        try:
            return self.inner.clean(value, model_instance)
        except ValidationError:
            raise

    def _resolve(self, instance: models.Model, raw: dict[str, Any]) -> Any:
        for language in fallback_chain(instance, self):
            if language in raw and raw[language] is not None:
                return self.inner.to_python(raw[language])
        if self.inner.has_default():
            return self.inner.get_default()
        return None

    def _json_map(self, instance: models.Model) -> dict[str, Any]:
        raw = instance.__dict__.get(self.attname)
        if isinstance(raw, dict):
            return dict(raw)
        return {}

    @staticmethod
    def _validate_inner(field: models.Field[Any, Any]) -> None:
        if isinstance(field, TranslatedField):
            raise TypeError("TranslatedField cannot wrap another TranslatedField.")
        if getattr(field, "is_relation", False) or isinstance(field, _DISALLOWED):
            raise TypeError(
                f"TranslatedField does not support {type(field).__name__}. "
                "Use a scalar field such as CharField, TextField, or DateField."
            )


def _register(cls: type[models.Model], name: str) -> None:
    current = cls.__dict__.get("_py_translations_field_names")
    inherited = getattr(cls, "_py_translations_field_names", ())
    names = list(current if current is not None else inherited)
    if name not in names:
        names.append(name)
    cls._py_translations_field_names = names  # type: ignore[attr-defined]
