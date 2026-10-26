__all__ = ["TranslatedField", "TranslatableModel", "json_translation_index"]
__version__ = "0.1.0"


def __getattr__(name):
    if name == "TranslatedField":
        from py_translations.fields import TranslatedField

        return TranslatedField
    if name == "TranslatableModel":
        from py_translations.models import TranslatableModel

        return TranslatableModel
    if name == "json_translation_index":
        from py_translations.indexes import json_translation_index

        return json_translation_index
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
