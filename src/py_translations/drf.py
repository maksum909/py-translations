from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils.translation import get_language

from py_translations.conf import get_default_language
from py_translations.languages import validate_language
from py_translations.storage import field_names, get_translated_field, require_translated_field

try:
    from rest_framework import serializers
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "TranslatableModelSerializer requires djangorestframework. "
        "Install it with the django-py-translations[drf] extra."
    ) from exc


def request_language(context: dict) -> str | None:
    request = context.get("request")
    if request is None:
        return None
    params = getattr(request, "query_params", None)
    if params is None:
        params = getattr(request, "GET", {})
    language = params.get("lang")
    if language in (None, ""):
        return None
    if language == "*":
        return "*"
    return validate_language(language)


class TranslatedSerializerField(serializers.Field):
    def __init__(self, *args, model_field, **kwargs):
        self.model_field = model_field
        kwargs.setdefault("required", not model_field.inner.blank)
        kwargs.setdefault("allow_null", True)
        super().__init__(*args, **kwargs)

    def get_attribute(self, instance):
        language = self.context.get("py_translations_lang")
        if language == "*":
            return self.model_field.raw_map(instance)
        if language:
            instance._translation_language = language
        return getattr(instance, self.model_field.name)

    def to_representation(self, value):
        if isinstance(value, dict):
            return {
                language: self._export(item) for language, item in value.items() if item is not None
            }
        return self._export(value)

    def to_internal_value(self, data):
        if isinstance(data, dict):
            return {
                validate_language(str(language)): self._clean(value)
                for language, value in data.items()
            }
        return self._clean(data)

    def _clean(self, value):
        if value is None or value == "":
            if self.model_field.inner.blank or not self.required:
                return None if value is None else ""
            self.fail("required")
        try:
            return self.model_field.inner.clean(value, None)
        except ValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc

    def _export(self, value):
        if value is None:
            return None
        native = self.model_field.inner.to_python(value)
        if isinstance(native, datetime | date | time | Decimal | UUID):
            return native.isoformat() if isinstance(native, datetime | date | time) else str(native)
        return native


class TranslatableModelSerializer(serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        context = kwargs.get("context") or {}
        kwargs["context"] = context
        context["py_translations_lang"] = request_language(context)
        super().__init__(*args, **kwargs)

    def build_field(self, field_name, info, model_class, nested_depth):
        translated = get_translated_field(model_class, field_name)
        if translated is not None:
            return TranslatedSerializerField, {"model_field": translated}
        return super().build_field(field_name, info, model_class, nested_depth)

    def create(self, validated_data):
        translated = self._pop_translated(validated_data)
        instance = super().create(validated_data)
        self._apply(instance, translated)
        instance.save()
        return instance

    def update(self, instance, validated_data):
        translated = self._pop_translated(validated_data)
        instance = super().update(instance, validated_data)
        self._apply(instance, translated)
        instance.save()
        return instance

    def _pop_translated(self, validated_data: dict) -> dict:
        names = set(field_names(self.Meta.model))
        return {name: validated_data.pop(name) for name in list(validated_data) if name in names}

    def _apply(self, instance, translated: dict) -> None:
        requested = self.context.get("py_translations_lang")
        active = (
            requested
            if requested and requested != "*"
            else (get_language() or get_default_language())
        )
        for name, value in translated.items():
            field = require_translated_field(type(instance), name)
            if isinstance(value, dict):
                for code, item in value.items():
                    if item is None or item == "":
                        field.clear_language(instance, code)
                    else:
                        field.set_language(instance, code, item)
                continue
            if value is None or value == "":
                field.clear_language(instance, active)
            else:
                field.set_language(instance, active, value)
