import pytest
from django.urls import reverse

from tests.testapp.models import Article, Page

pytestmark = pytest.mark.django_db


def test_admin_change_form_contains_every_language(admin_client):
    article = Article.objects.create(slug="a", title="Hello", body="Body")
    url = reverse("admin:testapp_article_change", args=[article.pk])
    response = admin_client.get(url)
    assert response.status_code == 200
    body = response.content.decode()
    assert "title__uk" in body
    assert "title__en" in body
    assert "body__uk" in body


def test_admin_post_saves_all_languages(admin_client):
    article = Article.objects.create(slug="a", title="Old", body="Old body")
    url = reverse("admin:testapp_article_change", args=[article.pk])
    response = admin_client.post(
        url,
        {
            "slug": "a",
            "title__en": "Hello",
            "title__uk": "Привіт",
            "body__en": "Body",
            "body__uk": "Тіло",
            "published_on__en": "",
            "published_on__uk": "",
            "note_set-TOTAL_FORMS": "0",
            "note_set-INITIAL_FORMS": "0",
            "note_set-MIN_NUM_FORMS": "0",
            "note_set-MAX_NUM_FORMS": "1000",
        },
        follow=True,
    )
    assert response.status_code == 200
    article.refresh_from_db()
    assert article.get_translation("en")["title"] == "Hello"
    assert article.get_translation("uk")["title"] == "Привіт"
    assert article.get_translation("uk")["body"] == "Тіло"


def test_table_admin_saves_a_translation_row(admin_client):
    page = Page.objects.create(slug="p", title="Old")
    url = reverse("admin:testapp_page_change", args=[page.pk])
    response = admin_client.post(
        url,
        {
            "slug": "p",
            "title__en": "Hello",
            "title__uk": "Привіт",
            "body__en": "Body",
            "body__uk": "",
        },
        follow=True,
    )
    assert response.status_code == 200
    page.refresh_from_db()
    assert page.get_translation("uk") == {"title": "Привіт"}
    assert page.translations.filter(language_code="en", title="Hello").exists()
