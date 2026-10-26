from __future__ import annotations

from typing import Any, cast

from django.db import models
from django.db.models import F, FilteredRelation, Prefetch, Q
from django.db.models.constants import LOOKUP_SEP
from django.db.models.fields.json import KT
from django.db.models.query import ModelIterable, ValuesIterable
from django.db.utils import NotSupportedError

from py_translations.languages import get_active_language, prefetch_languages, validate_language
from py_translations.storage import (
    field_names,
    get_translated_field,
    prepare_instance,
    uses_table,
)


def _lookup_root(lookup: object) -> str:
    if isinstance(lookup, Prefetch):
        return lookup.prefetch_to.split(LOOKUP_SEP, 1)[0]
    return str(lookup).split(LOOKUP_SEP, 1)[0]


def _without_translations(lookups: tuple[object, ...]) -> tuple[object, ...]:
    return tuple(lookup for lookup in lookups if _lookup_root(lookup) != "translations")


def _has_translations_prefetch(lookups: tuple[object, ...]) -> bool:
    return any(_lookup_root(lookup) == "translations" for lookup in lookups)


def _is_lookup(field: Any, part: str) -> bool:
    inner = field.inner
    if part in inner.get_lookups():
        return True
    get_transform = getattr(inner, "get_transform", None)
    return bool(get_transform and get_transform(part) is not None)


def _filter_or_exclude(qs: Any, negate: bool, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    method = models.QuerySet._filter_or_exclude  # type: ignore[attr-defined]
    return method(qs, negate, args, kwargs)


class _RenamedValuesIterable(ValuesIterable):
    def __iter__(self):
        mapping = getattr(self.queryset, "_translated_value_names", {})
        for row in super().__iter__():
            yield {mapping.get(key, key): value for key, value in row.items()}


class TranslatableQuerySet(models.QuerySet):
    _prefetch_related_lookups: tuple[Any, ...]

    def __init__(self, model=None, query=None, using=None, hints=None):
        super().__init__(model=model, query=query, using=using, hints=hints)
        self._translation_language: str | None = None
        self._language_pinned = False
        self._translation_required = False
        self._prefetch_languages: tuple[str, ...] | None = None
        self._prefetch_all = False
        self._skip_translation_prefetch = False
        self._i18n_language: str | None = None

    def _clone(self):
        clone = super()._clone()
        clone._translation_language = self._translation_language
        clone._language_pinned = self._language_pinned
        clone._translation_required = self._translation_required
        clone._prefetch_languages = self._prefetch_languages
        clone._prefetch_all = self._prefetch_all
        clone._skip_translation_prefetch = self._skip_translation_prefetch
        clone._i18n_language = self._i18n_language
        clone._translated_value_names = getattr(self, "_translated_value_names", {})
        return clone

    def _copy(self) -> TranslatableQuerySet:
        return super()._chain()  # type: ignore[misc]

    def translated(self, language: str, *, required: bool = False):
        validate_language(language)
        clone = self._copy()
        clone._translation_language = language
        clone._language_pinned = True
        clone._translation_required = required
        if not required:
            return clone
        if uses_table(clone.model):
            clone = clone._with_i18n(language)
            return _filter_or_exclude(clone, False, (), {"_i18n__language_code": language})
        required_q: Q | None = None
        for name in field_names(clone.model):
            piece = Q(**{f"{name}__{language}__isnull": False})
            required_q = piece if required_q is None else required_q | piece
        if required_q is None:
            return clone
        return _filter_or_exclude(clone, False, (required_q,), {})

    language = translated

    def with_translations(self, *languages: str):
        clone = self._copy()
        if not uses_table(clone.model):
            return clone
        for language in languages:
            validate_language(language)
        clone._prefetch_languages = languages
        clone._prefetch_all = not languages
        clone._skip_translation_prefetch = False
        clone._prefetch_related_lookups = _without_translations(clone._prefetch_related_lookups)
        return clone

    def defer_translations(self):
        clone = self._copy()
        clone._skip_translation_prefetch = True
        clone._prefetch_related_lookups = _without_translations(clone._prefetch_related_lookups)
        return clone

    def translated_values(self, *names: str):
        language = self._query_language()
        plain: list[str] = []
        annotations: dict[str, Any] = {}
        rename = {}
        needs_join = False
        for name in names:
            field = get_translated_field(self.model, name)
            if field is None:
                plain.append(name)
                continue
            alias = f"_tr_{name}"
            rename[alias] = name
            if field.backend == "json":
                annotations[alias] = KT(f"{name}__{language}")
            else:
                needs_join = True
                annotations[alias] = F(f"_i18n__{name}")
        qs = self._with_i18n(language) if needs_join else self
        qs = qs._prepare_language(language, bool(annotations))
        values = qs.annotate(**annotations).values(*plain, *annotations)
        values._translated_value_names = rename
        values._iterable_class = _RenamedValuesIterable
        return values

    def filter(self, *args, **kwargs):
        qs, args, kwargs = self._prepare_call(args, kwargs)
        return _filter_or_exclude(qs, False, args, kwargs)

    def exclude(self, *args, **kwargs):
        qs, args, kwargs = self._prepare_call(args, kwargs)
        return _filter_or_exclude(qs, True, args, kwargs)

    def order_by(self, *field_names):
        language = self._query_language()
        rewritten = []
        touched = False
        for name in field_names:
            if not isinstance(name, str):
                rewritten.append(name)
                continue
            descending = name.startswith("-")
            raw = name[1:] if descending else name
            piece, did = self._rewrite_ordering(raw, language, descending)
            rewritten.append(piece)
            touched = touched or did
        qs = self._prepare_language(language, touched)
        return super(TranslatableQuerySet, qs).order_by(*rewritten)

    def update(self, **kwargs):
        hit = sorted(set(field_names(self.model)).intersection(kwargs))
        if hit:
            raise NotSupportedError(
                f"QuerySet.update() cannot set translated fields ({', '.join(hit)}). "
                "Save instances with set_translation()."
            )
        return super().update(**kwargs)

    def only(self, *fields):
        extra = [
            name
            for name in field_names(self.model)
            if name not in fields and not uses_table(self.model)
        ]
        return super().only(*fields, *extra)

    def defer(self, *fields):
        blocked = set(field_names(self.model)) if not uses_table(self.model) else set()
        kept = [field for field in fields if field.split(LOOKUP_SEP, 1)[0] not in blocked]
        if not kept:
            return self._copy()
        return super().defer(*kept)

    def iterator(self, chunk_size=None):
        self._install_prefetch()
        if chunk_size is None and self._prefetch_related_lookups:
            chunk_size = 2000
        for obj in super().iterator(chunk_size=chunk_size):
            if isinstance(obj, models.Model):
                prepare_instance(
                    obj,
                    language=self._translation_language,
                    pinned=self._language_pinned,
                )
            yield obj

    async def aiterator(self, chunk_size=2000):
        self._install_prefetch()
        async for obj in super().aiterator(chunk_size=chunk_size):
            if isinstance(obj, models.Model):
                prepare_instance(
                    obj,
                    language=self._translation_language,
                    pinned=self._language_pinned,
                )
            yield obj

    def _fetch_all(self):
        self._install_prefetch()
        super()._fetch_all()
        self._prepare_results()

    def _prepare_call(self, args: tuple, kwargs: dict):
        language = self._query_language()
        rewritten_args = []
        touched = False
        for arg in args:
            new_arg, did = self._rewrite_q(arg, language)
            rewritten_args.append(new_arg)
            touched = touched or did
        new_kwargs = {}
        for key, value in kwargs.items():
            new_key, did = self._rewrite_key(key, language)
            new_kwargs[new_key] = value
            touched = touched or did
        return self._prepare_language(language, touched), tuple(rewritten_args), new_kwargs

    def _prepare_language(self, language: str, touched: bool):
        if not touched:
            return self
        qs = self._with_i18n(language) if uses_table(self.model) else self
        if qs._language_pinned:
            return qs
        if qs is self:
            qs = self._copy()
        qs._translation_language = language
        qs._language_pinned = True
        return qs

    def _with_i18n(self, language: str):
        if not uses_table(self.model):
            return self
        # The alias is not "translations": prefetch_related() rejects a
        # FilteredRelation registered under the same name as the relation.
        if self._i18n_language == language and "_i18n" in self.query.annotations:
            return self
        if self._i18n_language and self._i18n_language != language:
            raise ValueError(
                f"This queryset already joined translations for {self._i18n_language!r}. "
                f"Start a new queryset to use {language!r}."
            )
        clone = self.annotate(
            _i18n=FilteredRelation(
                "translations",
                condition=Q(translations__language_code=language),
            )
        )
        clone._i18n_language = language
        return clone

    def _query_language(self) -> str:
        if self._translation_language:
            return self._translation_language
        return get_active_language()

    def _rewrite_q(self, node, language: str):
        if not isinstance(node, Q):
            return node, False
        children = []
        touched = False
        for child in cast(tuple[Any, ...], node.children):
            if isinstance(child, Q):
                rewritten, did = self._rewrite_q(child, language)
                children.append(rewritten)
                touched = touched or did
            else:
                key, value = child
                new_key, did = self._rewrite_key(key, language)
                children.append((new_key, value))
                touched = touched or did
        return Q(*children, _connector=node.connector, _negated=node.negated), touched

    def _rewrite_key(self, key: str, language: str):
        parts = key.split(LOOKUP_SEP)
        field = get_translated_field(self.model, parts[0])
        if field is None:
            return key, False
        rest = parts[1:]
        if rest and not _is_lookup(field, rest[0]):
            language = validate_language(rest[0])
            rest = rest[1:]
        if not rest:
            rest = ["exact"]
        if field.backend == "json":
            return LOOKUP_SEP.join([parts[0], language, *rest]), True
        return LOOKUP_SEP.join(["_i18n", parts[0], *rest]), True

    def _rewrite_ordering(self, raw: str, language: str, descending: bool):
        parts = raw.split(LOOKUP_SEP)
        field = get_translated_field(self.model, parts[0])
        if field is None:
            prefix = "-" if descending else ""
            return f"{prefix}{raw}", False
        rest = parts[1:]
        if rest and not _is_lookup(field, rest[0]):
            language = validate_language(rest[0])
        if field.backend == "json":
            expr = KT(f"{parts[0]}__{language}")
            return (expr.desc() if descending else expr.asc()), True
        prefix = "-" if descending else ""
        return f"{prefix}_i18n__{parts[0]}", True

    def _install_prefetch(self) -> None:
        if self._iterable_class is not ModelIterable:
            return
        if not uses_table(self.model) or self._skip_translation_prefetch:
            return
        if _has_translations_prefetch(self._prefetch_related_lookups):
            return
        self._prefetch_related_lookups = (
            *self._prefetch_related_lookups,
            self._translation_prefetch(),
        )

    def _translation_prefetch(self) -> Prefetch:
        model = self.model._py_translation_model  # type: ignore[attr-defined]
        qs = model._default_manager.all()
        if self._prefetch_languages:
            qs = qs.filter(language_code__in=self._prefetch_languages)
        elif not self._prefetch_all and self._language_pinned and self._translation_language:
            languages = prefetch_languages(self.model, self._translation_language)
            if languages:
                qs = qs.filter(language_code__in=languages)
        return Prefetch("translations", queryset=qs)

    def _prepare_results(self) -> None:
        if self._iterable_class is not ModelIterable or not self._result_cache:
            return
        for obj in self._result_cache:
            if isinstance(obj, models.Model):
                prepare_instance(
                    obj,
                    language=self._translation_language,
                    pinned=self._language_pinned,
                )


TranslatableManager = models.Manager.from_queryset(TranslatableQuerySet)
