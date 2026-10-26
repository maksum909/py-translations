import pytest
from django.core.management import call_command

from tests.testapp.models import Article, LegacyArticleTranslation

pytestmark = pytest.mark.django_db


def test_migrate_parler_copies_rows():
    article = Article.objects.create(slug="a", title="Temp", body="Temp")
    LegacyArticleTranslation.objects.create(
        master=article, language_code="en", title="Hello", body="Body"
    )
    LegacyArticleTranslation.objects.create(
        master=article, language_code="uk", title="Привіт", body="Тіло"
    )
    call_command(
        "migrate_parler",
        "--from-model",
        "testapp.LegacyArticleTranslation",
        "--to-model",
        "testapp.Article",
    )
    article.refresh_from_db()
    assert article.get_translation("en")["title"] == "Hello"
    assert article.get_translation("uk")["body"] == "Тіло"


def test_migrate_parler_dry_run_does_not_write():
    article = Article.objects.create(slug="a", title="Keep", body="Keep")
    LegacyArticleTranslation.objects.create(
        master=article, language_code="uk", title="Привіт", body="Тіло"
    )
    call_command(
        "migrate_parler",
        "--from-model",
        "testapp.LegacyArticleTranslation",
        "--to-model",
        "testapp.Article",
        "--dry-run",
    )
    article.refresh_from_db()
    assert article.get_translation("uk") == {}
    assert article.get_translation("en")["title"] == "Keep"
