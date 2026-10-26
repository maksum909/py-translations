from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import translation

from py_translations import TranslatedField
from py_translations.exceptions import UnloadedTranslation
from tests.testapp.models import Article, ConcreteChild, Doc, Manual, Page

pytestmark = pytest.mark.django_db


def test_json_round_trip_uses_active_language():
    article = Article.objects.create(slug="a", title="Hello", body="Body")
    article.refresh_from_db()
    assert article.title == "Hello"
    assert article.body == "Body"
    assert article.get_translation("en")["title"] == "Hello"


def test_set_translation_and_fallback():
    article = Article.objects.create(slug="a")
    article.set_translation("en", title="Hello", body="Body")
    article.set_translation("uk", title="Привіт")
    article.save()

    translation.activate("uk")
    loaded = Article.objects.get(pk=article.pk)
    assert loaded.title == "Привіт"
    assert loaded.body == "Body"
    assert loaded.has_translation("uk", "title")
    assert not loaded.has_translation("uk", "body")


def test_empty_string_does_not_fall_back():
    article = Article(slug="a")
    article.set_translation("en", title="Hello", body="Body")
    article.set_translation("uk", title="", body="Тіло")
    article.save()
    translation.activate("uk")
    loaded = Article.objects.get(pk=article.pk)
    assert loaded.title == ""
    assert loaded.body == "Тіло"


def test_field_fallback_overrides_project(settings):
    settings.PY_TRANSLATIONS = {
        **settings.PY_TRANSLATIONS,
        "FALLBACKS": {"uk": []},
    }
    article = Article.objects.create(slug="a")
    article.set_translation("en", title="Hello", body="Body")
    article.save()
    translation.activate("uk")
    loaded = Article.objects.get(pk=article.pk)
    assert loaded.title is None
    assert loaded.body == "Body"


def test_model_fallback_chain():
    manual = Manual.objects.create(slug="m")
    manual.set_translation("en", title="Hello")
    manual.save()
    translation.activate("de")
    assert Manual.objects.get(pk=manual.pk).title == "Hello"


def test_date_round_trip():
    article = Article.objects.create(
        slug="a", title="Hello", body="Body", published_on=date(2024, 1, 2)
    )
    loaded = Article.objects.get(pk=article.pk)
    assert loaded.published_on == date(2024, 1, 2)


def test_as_language_does_not_stick():
    article = Article.objects.create(slug="a", title="Hello", body="Body")
    article.set_translation("uk", title="Привіт")
    article.save()
    with article.as_language("uk"):
        assert article.title == "Привіт"
    assert article.title == "Hello"


def test_delete_translation():
    article = Article.objects.create(slug="a", title="Hello", body="Body")
    article.set_translation("uk", title="Привіт")
    article.save()
    article.delete_translation("uk")
    article.save()
    translation.activate("uk")
    assert Article.objects.get(pk=article.pk).title == "Hello"


def test_table_round_trip_and_fallback():
    page = Page.objects.create(slug="p", title="Hello", body="Body")
    page.set_translation("uk", title="Привіт")
    page.save()
    translation.activate("uk")
    loaded = Page.objects.get(pk=page.pk)
    assert loaded.title == "Привіт"
    assert loaded.body == "Body"
    assert loaded.get_available_languages() == ["en", "uk"]


def test_table_delete_translation():
    page = Page.objects.create(slug="p", title="Hello")
    page.set_translation("uk", title="Привіт")
    page.save()
    page.delete_translation("uk")
    page.save()
    assert page.translations.filter(language_code="uk").count() == 0


def test_unloaded_table_translation_raises():
    page = Page.objects.create(slug="p", title="Hello")
    bare = Page.objects.defer_translations().get(pk=page.pk)
    with pytest.raises(UnloadedTranslation):
        _ = bare.title


def test_full_clean_requires_active_language():
    article = Article(slug="a")
    with pytest.raises(ValidationError):
        article.full_clean()


def test_abstract_parent_field_is_concrete_on_child():
    doc = Doc.objects.create(slug="d", title="Doc")
    assert Doc.objects.get(pk=doc.pk).title == "Doc"
    assert isinstance(Doc._meta.get_field("title"), TranslatedField)


def test_multi_table_inheritance_is_rejected():
    errors = ConcreteChild.check()
    assert any(error.id == "py_translations.E001" for error in errors)


def test_deconstruct_round_trip():
    field = Article._meta.get_field("title")
    _name, path, _args, kwargs = field.deconstruct()
    assert path == "py_translations.fields.TranslatedField"
    assert kwargs["field"].max_length == 200


def test_relation_field_is_rejected():
    with pytest.raises(TypeError):
        TranslatedField(models.ForeignKey("auth.User", on_delete=models.CASCADE))


def test_invalid_language_code():
    article = Article(slug="a")
    with pytest.raises(ValueError):
        article.set_translation("bad__code", title="x")
