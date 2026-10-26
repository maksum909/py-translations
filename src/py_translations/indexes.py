from __future__ import annotations

from django.db import models
from django.db.models.fields.json import KT

from py_translations.languages import validate_language


def json_translation_index(field: str, language: str, *, name: str) -> models.Index:
    """Expression index on one language of a JSON translation column.

    Useful on PostgreSQL and SQLite. MySQL only if the server supports
    functional indexes.
    """
    validate_language(language)
    return models.Index(KT(f"{field}__{language}"), name=name)
