class UnloadedTranslation(RuntimeError):
    """The instance has no translation cache and no prefetch to fill it."""


class TranslationError(Exception):
    """Base error for invalid translation operations."""
