# py-translations

Typed translations for Django model fields. One line per field. A JSON column by default, or a real translation table when a language needs its own index.

```python
class Article(TranslatableModel):
    class Translations:
        backend = "json"  # or "table"
        fallbacks = {"uk": ["en"]}

    slug = models.SlugField()
    title = TranslatedField(models.CharField(max_length=200))
    body = TranslatedField(models.TextField(), fallback=["en"])
```

`article.title` is the string for the active language. The active language is the one pinned on the instance, then `django.utils.translation.get_language()`, then `PY_TRANSLATIONS["DEFAULT_LANGUAGE"]`, then `settings.LANGUAGE_CODE`.

## Install

```bash
pip install py-translations
```

Add `py_translations` to `INSTALLED_APPS`. Django REST framework is an extra:

```bash
pip install py-translations[drf]
```

Django 4.2+ and Python 3.10+. Django 4.2 left extended support in April 2026; it stays in the test matrix because projects still run it. Current targets are 5.2 LTS, 6.0, and 6.1.

## Settings

```python
PY_TRANSLATIONS = {
    "BACKEND": "json",
    "DEFAULT_LANGUAGE": "en",
    "LANGUAGES": ["uk", "en"],  # or settings.LANGUAGES
    "FALLBACKS": {"uk": ["en"], "*": ["en"]},
}
```

A new language is a new key or a new row. Neither backend needs a schema migration to add one.

## Backends

Pick one backend per model. A child model cannot switch the backend a parent already used for its fields.

**JSON** stores each translated field in its own JSON column, default `{}`. A list and a read are one query. There is no join. An index for one language is explicit:

```python
from py_translations import json_translation_index

class Meta:
    indexes = [json_translation_index("title", "uk", name="article_title_uk")]
```

`max_length` on a JSON field is checked in Python.

**Table** creates `{App}{Model}I18n` with `db_table` `{app}_{model}_i18n`, a `master` foreign key (`CASCADE`, `related_name="translations"`), `language_code`, and one real column per translated field (`null=True`, `blank=True`). Unique together on `(master, language_code)`. A list is two queries: the masters, then a prefetch. `count()` and `exists()` do not prefetch. The descriptor itself never queries.

## Reading and writing

```python
article.title = "Привіт"                 # writes the active language
article.set_translation("en", title="Hello", body="Body")
article.get_translation("uk")            # {"title": "...", "body": "..."}
article.delete_translation("en")

with article.as_language("en"):
    article.title
```

Missing key and `None` fall through the fallback chain. An empty string is a stored value and does not fall through. Fallback runs in Python when you read the attribute. `filter()` and `order_by()` use one language, the queryset language, and do not walk the chain.

Field `fallback=[...]` replaces the chain for that field. `fallback=[]` disables it. Otherwise the model `Translations.fallbacks` is used, then the project `FALLBACKS`.

## QuerySet

```python
Article.objects.translated("uk").filter(title__icontains="ривіт")
Article.objects.translated("uk", required=True)   # hide rows with no "uk" value
Article.objects.filter(title__en="Hello")         # explicit language wins
Page.objects.translated("uk").order_by("title")
Page.objects.with_translations("uk", "en")
Page.objects.defer_translations()                 # a later read raises UnloadedTranslation
```

`.language()` is an alias of `.translated()`. Calling `.translated()` again with a different language, after a table queryset has already joined, raises `ValueError`.

`values("title")` returns the raw JSON object. Django's values iterator does not go through the descriptor. Use `translated_values("title")` for the string of the active language.

`QuerySet.update(title=...)` raises `NotSupportedError`. `F("title")` is not rewritten.

JSON ordering uses Django's `KT` lookup. The table backend filters through a `FilteredRelation` aliased `_i18n` and prefetches the real relation `translations`.

## Admin and DRF

```python
from py_translations.admin import TranslatableAdmin, TranslatableStackedInline

@admin.register(Article)
class ArticleAdmin(TranslatableAdmin):
    pass
```

The change form shows every configured language and saves them in one POST. A blank input removes that language's value. On the default language, `blank=False` on the inner field is still required.

```python
from py_translations.drf import TranslatableModelSerializer

class ArticleSerializer(TranslatableModelSerializer):
    class Meta:
        model = Article
        fields = ["slug", "title", "body"]
```

`?lang=uk` returns strings. `?lang=*` returns the language maps. A string writes the requested language. A dict writes each language; an empty string clears that language.

## Coming from django-parler

```bash
python manage.py migrate_parler \
    --from-model app.ArticleTranslation \
    --to-model app.Article
```

`--dry-run` prints the count and writes nothing. The command copies overlapping translated fields and keeps the parler rows. The table name is `*_i18n`, so a parler `*_translation` table can sit beside it during the move.

| | parler | py-translations |
| --- | --- | --- |
| Storage | A translation row and a join | JSON column, or a table when you ask for one |
| `obj.title` | Often a query inside the descriptor | The value already loaded with the instance |
| Types | `TranslatedFields(**kwargs)` is untyped | `TranslatedField(CharField(...))` is `str` |
| Fallback | Extra queries, `TranslationDoesNotExist` | Python chain on attribute access |
| Admin | A tab is a new GET and saves one language | One form, one POST, every language |
| API | django-parler-rest, a nested list | `?lang=` on the model serializer |
| Async | The descriptor uses the sync ORM | `aget` / `asave` / `aiterator`, no query in the descriptor |
| New language | A new row, but the implicit model is fragile | A new key or row, no migration |

## Limits

- Multi-table inheritance is rejected (`py_translations.E001`).
- No `FileField`, relations, `BinaryField`, `AutoField`, or a translated field inside a translated field.
- No automatic unique constraint per language. Add a `UniqueConstraint` yourself on the table backend.
- Async is Django's `sync_to_async` wrappers, not a separate query compiler.
- Custom managers should subclass `TranslatableManager`.

## Tests

```bash
pytest
ruff check .
mypy src/py_translations
python benchmarks/bench.py --n 10000
```

`benchmarks/bench.py` times JSON against the table backend on SQLite. It is not part of CI. Postgres is the useful comparison for the index case.
