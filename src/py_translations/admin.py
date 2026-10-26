from __future__ import annotations

from django.contrib import admin

from py_translations.conf import configured_languages, language_label
from py_translations.forms import (
    TranslatableModelForm,
    build_translatable_form,
    editable_form_fields,
)
from py_translations.storage import field_names


class TranslatableAdmin(admin.ModelAdmin):
    form = TranslatableModelForm

    def get_form(self, request, obj=None, change=False, **kwargs):
        kwargs["form"] = build_translatable_form(self.model)
        kwargs["fields"] = editable_form_fields(self.model)
        return super().get_form(request, obj, change=change, **kwargs)

    def get_fieldsets(self, request, obj=None):
        translated = set(field_names(self.model))
        concrete = tuple(
            name
            for name in editable_form_fields(self.model)
            if "__" not in name and name not in translated
        )
        fieldsets = [(None, {"fields": concrete})]
        for language in configured_languages():
            names = tuple(f"{name}__{language}" for name in field_names(self.model))
            fieldsets.append(
                (
                    language_label(language),
                    {"fields": names, "classes": ("py-translations-lang", f"lang-{language}")},
                )
            )
        return fieldsets


class _InlineFormMixin:
    form = TranslatableModelForm

    def get_formset(self, request, obj=None, **kwargs):
        kwargs["form"] = build_translatable_form(self.model)
        parent = getattr(self, "parent_model", None)
        fields = []
        for name in editable_form_fields(self.model):
            try:
                model_field = self.model._meta.get_field(name)
            except Exception:
                fields.append(name)
                continue
            remote = getattr(model_field, "remote_field", None)
            if remote is not None and parent is not None and remote.model == parent:
                continue
            fields.append(name)
        kwargs["fields"] = fields
        return super().get_formset(request, obj, **kwargs)


class TranslatableStackedInline(_InlineFormMixin, admin.StackedInline):  # type: ignore[misc]
    pass


class TranslatableTabularInline(_InlineFormMixin, admin.TabularInline):  # type: ignore[misc]
    pass
