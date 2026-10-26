from __future__ import annotations

import sys

from django.db import models

from py_translations.storage import field_names, require_translated_field


def create_translation_model(model: type[models.Model]) -> type[models.Model]:
    existing = getattr(model, "_py_translation_model", None)
    if existing is not None:
        return existing

    app_label = model._meta.app_label
    class_name = f"{model.__name__}I18n"
    db_table = f"{app_label}_{model._meta.model_name}_i18n"
    names = field_names(model)
    if not names:
        raise ValueError(f"{model.__name__} uses the table backend but has no translated fields.")

    attrs: dict[str, object] = {
        "__module__": model.__module__,
        "Meta": type(
            "Meta",
            (),
            {
                "app_label": app_label,
                "db_table": db_table,
                "constraints": [
                    models.UniqueConstraint(
                        fields=["master", "language_code"],
                        name=f"{db_table}_uniq"[:63],
                    )
                ],
                "indexes": [
                    models.Index(fields=["language_code"], name=f"{db_table}_lang"[:63]),
                ],
            },
        ),
        "master": models.ForeignKey(
            model,
            related_name="translations",
            on_delete=models.CASCADE,
        ),
        "language_code": models.CharField(max_length=32),
    }
    for name in names:
        source = require_translated_field(model, name)
        cloned = source.inner.clone()
        cloned.null = True
        cloned.blank = True
        cloned.primary_key = False
        cloned._unique = False
        cloned.db_index = False
        cloned.default = models.NOT_PROVIDED
        attrs[name] = cloned

    translation_model = type(class_name, (models.Model,), attrs)
    model._py_translation_model = translation_model  # type: ignore[attr-defined]
    module = sys.modules.get(model.__module__)
    if module is not None and not hasattr(module, class_name):
        setattr(module, class_name, translation_model)
    return translation_model
