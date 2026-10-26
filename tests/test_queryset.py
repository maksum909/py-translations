import pytest
from asgiref.sync import async_to_sync
from django.db import connection
from django.db.utils import NotSupportedError
from django.test.utils import CaptureQueriesContext
from django.utils import translation

from tests.testapp.models import Article, Page

pytestmark = pytest.mark.django_db


def _article(slug, **translations):
    article = Article(slug=slug)
    for language, payload in translations.items():
        article.set_translation(language, **payload)
    article.save()
    return article


def test_filter_and_order_use_one_language():
    greeting = _article(
        "a", uk={"title": "Привіт", "body": "Тіло"}, en={"title": "Hello", "body": "Body"}
    )
    _article("b", uk={"title": "Світ", "body": "Інше"}, en={"title": "World", "body": "Other"})

    uk = list(Article.objects.translated("uk").filter(title__icontains="ривіт"))
    assert uk == [greeting]
    en = list(Article.objects.translated("en").filter(title="Hello"))
    assert en == [greeting]
    ordered = [item.slug for item in Article.objects.translated("uk").order_by("title")]
    assert ordered == ["a", "b"]


def test_explicit_language_lookup_beats_queryset_language():
    article = _article(
        "a", uk={"title": "Привіт", "body": "Тіло"}, en={"title": "Hello", "body": "Body"}
    )
    found = Article.objects.translated("en").filter(title__uk="Привіт")
    assert list(found) == [article]


def test_q_object_is_rewritten():
    article = _article("a", en={"title": "Hello", "body": "Body"})
    found = Article.objects.translated("en").filter(models_q(article))
    assert list(found) == [article]


def models_q(article):
    from django.db.models import Q

    return Q(title="Hello") | Q(slug="missing")


def test_filter_does_not_apply_fallback():
    _article("a", en={"title": "Hello", "body": "Body"})
    assert not Article.objects.translated("uk").filter(title="Hello").exists()


def test_json_reads_are_one_query():
    _article("a", en={"title": "Hello", "body": "Body"}, uk={"title": "Привіт", "body": "Тіло"})
    with CaptureQueriesContext(connection) as ctx:
        rows = list(Article.objects.translated("uk"))
        assert [row.title for row in rows] == ["Привіт"]
    assert len(ctx.captured_queries) == 1


def test_table_reads_are_two_queries():
    page = Page.objects.create(slug="p")
    page.set_translation("en", title="Hello", body="Body")
    page.set_translation("uk", title="Привіт")
    page.save()
    with CaptureQueriesContext(connection) as ctx:
        rows = list(Page.objects.translated("uk"))
        assert [row.title for row in rows] == ["Привіт"]
        assert rows[0].body == "Body"
    assert len(ctx.captured_queries) == 2


def test_two_languages_do_not_duplicate_rows():
    page = Page.objects.create(slug="p", title="Hello")
    page.set_translation("uk", title="Привіт")
    page.save()
    assert Page.objects.translated("uk").filter(title="Привіт").count() == 1


def test_values_returns_raw_json_and_translated_values_returns_text():
    article = _article(
        "a", uk={"title": "Привіт", "body": "Тіло"}, en={"title": "Hello", "body": "Body"}
    )
    raw = Article.objects.filter(pk=article.pk).values("title").get()
    assert raw["title"]["uk"] == "Привіт"
    resolved = Article.objects.translated("uk").translated_values("title").get()
    assert resolved["title"] == "Привіт"


def test_table_order_and_translated_values():
    first = Page.objects.create(slug="a")
    second = Page.objects.create(slug="b")
    first.set_translation("uk", title="Яблуко")
    second.set_translation("uk", title="Банан")
    first.save()
    second.save()
    ordered = [page.slug for page in Page.objects.translated("uk").order_by("title")]
    assert ordered == ["b", "a"]
    values = list(
        Page.objects.translated("uk").order_by("title").translated_values("slug", "title")
    )
    assert [row["title"] for row in values] == ["Банан", "Яблуко"]


def test_required_hides_rows_without_that_language():
    present = _article("a", uk={"title": "Привіт", "body": "Тіло"})
    _article("b", en={"title": "Hello", "body": "Body"})
    found = list(Article.objects.translated("uk", required=True))
    assert found == [present]


def test_update_of_translated_field_is_rejected():
    _article("a", en={"title": "Hello", "body": "Body"})
    with pytest.raises(NotSupportedError):
        Article.objects.update(title="x")


def test_async_get_and_save():
    article = _article("a", en={"title": "Hello", "body": "Body"})

    async def read():
        loaded = await Article.objects.translated("en").aget(pk=article.pk)
        assert loaded.title == "Hello"
        loaded.set_translation("uk", title="Привіт")
        await loaded.asave()

    async_to_sync(read)()
    translation.activate("uk")
    assert Article.objects.get(pk=article.pk).title == "Привіт"


def test_count_does_not_prefetch():
    Page.objects.create(slug="p", title="Hello")
    with CaptureQueriesContext(connection) as ctx:
        assert Page.objects.count() == 1
    assert len(ctx.captured_queries) == 1
