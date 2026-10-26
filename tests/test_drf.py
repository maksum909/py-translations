import pytest

from py_translations.drf import TranslatableModelSerializer
from tests.testapp.models import Article, Page

pytestmark = pytest.mark.django_db


class ArticleSerializer(TranslatableModelSerializer):
    class Meta:
        model = Article
        fields = ["id", "slug", "title", "body"]


class PageSerializer(TranslatableModelSerializer):
    class Meta:
        model = Page
        fields = ["id", "slug", "title", "body"]


class Request:
    def __init__(self, lang=None):
        self.query_params = {} if lang is None else {"lang": lang}


def test_serializer_resolves_lang_query():
    article = Article(slug="a")
    article.set_translation("en", title="Hello", body="Body")
    article.set_translation("uk", title="Привіт", body="Тіло")
    article.save()
    data = ArticleSerializer(article, context={"request": Request("uk")}).data
    assert data["title"] == "Привіт"
    assert data["body"] == "Тіло"


def test_serializer_all_languages():
    article = Article(slug="a")
    article.set_translation("en", title="Hello", body="Body")
    article.set_translation("uk", title="Привіт", body="Тіло")
    article.save()
    data = ArticleSerializer(article, context={"request": Request("*")}).data
    assert data["title"] == {"en": "Hello", "uk": "Привіт"}


def test_serializer_writes_string_and_dict():
    article = Article.objects.create(slug="a", title="Hello", body="Body")
    serializer = ArticleSerializer(
        article,
        data={"slug": "a", "title": "Привіт", "body": "Тіло"},
        context={"request": Request("uk")},
    )
    assert serializer.is_valid(), serializer.errors
    saved = serializer.save()
    assert saved.get_translation("uk")["title"] == "Привіт"
    assert saved.get_translation("en")["title"] == "Hello"

    page = Page.objects.create(slug="p", title="Hello", body="Body")
    page_serializer = PageSerializer(
        page,
        data={"slug": "p", "title": {"en": "Hello", "uk": "Привіт"}, "body": "Body"},
        context={"request": Request("*")},
    )
    assert page_serializer.is_valid(), page_serializer.errors
    saved_page = page_serializer.save()
    assert saved_page.get_translation("uk")["title"] == "Привіт"


def test_serializer_create():
    serializer = ArticleSerializer(
        data={"slug": "created", "title": "Hello", "body": "Body"},
        context={"request": Request("en")},
    )
    assert serializer.is_valid(), serializer.errors
    article = serializer.save()
    assert article.title == "Hello"
