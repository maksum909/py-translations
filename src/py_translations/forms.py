from __future__ import annotations

from django import forms

from py_translations.conf import configured_languages, get_default_language
from py_translations.exceptions import UnloadedTranslation
from py_translations.models import TranslatableModel
from py_translations.storage import field_names, get_translated_field, require_translated_field


class TranslatableModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        model = self._meta.model
        if not issubclass(model, TranslatableModel):
            return
        instance = self.instance
        for name in field_names(model):
            self.fields.pop(name, None)
            field = get_translated_field(model, name)
            raw = _raw(instance, field)
            for language in configured_languages():
                key = f"{name}__{language}"
                if key not in self.fields:
                    continue
                if language in raw and raw[language] is not None:
                    initial = field.inner.to_python(raw[language])
                    self.fields[key].initial = initial
                    self.initial[key] = initial

    def save(self, commit=True):
        instance = super().save(commit=False)
        self.write_translations(instance)
        if commit:
            instance.save()
            self.save_m2m()
        return instance

    def write_translations(self, instance) -> None:
        languages = configured_languages()
        for name in field_names(type(instance)):
            field = require_translated_field(type(instance), name)
            raw = _raw(instance, field)
            for language in languages:
                key = f"{name}__{language}"
                if key not in self.cleaned_data:
                    continue
                value = self.cleaned_data[key]
                current = raw.get(language)
                if value is None or value == "":
                    if current not in (None, ""):
                        field.clear_language(instance, language)
                    continue
                if current != value:
                    field.set_language(instance, language, value)


def editable_form_fields(model) -> list[str]:
    names = [
        field.name
        for field in model._meta.concrete_fields
        if field.editable and not field.auto_created and field.name not in set(field_names(model))
    ]
    for name in field_names(model):
        for language in configured_languages():
            names.append(f"{name}__{language}")
    return names


def build_translatable_form(model, base=TranslatableModelForm):
    languages = configured_languages()
    default = get_default_language()
    declared: dict[str, forms.Field] = {}
    for name in field_names(model):
        source = get_translated_field(model, name)
        for language in languages:
            form_field = source.inner.formfield()
            if form_field is None:
                continue
            form_field.required = (not source.inner.blank) and language == default
            label = source.inner.verbose_name or name.replace("_", " ")
            form_field.label = f"{label} [{language}]"
            declared[f"{name}__{language}"] = form_field
    return type(f"{model.__name__}TranslationForm", (base,), declared)


def _raw(instance, field) -> dict:
    if instance is None or not getattr(instance, "pk", None):
        return {}
    try:
        return field.raw_map(instance)
    except UnloadedTranslation:
        instance.load_translations()
        return field.raw_map(instance)
