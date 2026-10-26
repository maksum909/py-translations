from django.db import models

from py_translations import TranslatableModel, TranslatedField


class Article(TranslatableModel):
    slug = models.SlugField()
    title = TranslatedField(models.CharField(max_length=200))
    body = TranslatedField(models.TextField(), fallback=["en"])
    published_on = TranslatedField(models.DateField(null=True, blank=True))


class Page(TranslatableModel):
    class Translations:
        backend = "table"

    slug = models.SlugField()
    title = TranslatedField(models.CharField(max_length=200))
    body = TranslatedField(models.TextField(blank=True))


class Note(TranslatableModel):
    article = models.ForeignKey(Article, on_delete=models.CASCADE)
    title = TranslatedField(models.CharField(max_length=100))


class Manual(TranslatableModel):
    class Translations:
        fallbacks = {"de": ["en"]}

    slug = models.SlugField()
    title = TranslatedField(models.CharField(max_length=200))


class AbstractDoc(TranslatableModel):
    title = TranslatedField(models.CharField(max_length=100))

    class Meta:
        abstract = True


class Doc(AbstractDoc):
    slug = models.SlugField()


class ConcreteBase(TranslatableModel):
    slug = models.SlugField()
    title = TranslatedField(models.CharField(max_length=20))


class ConcreteChild(ConcreteBase):
    extra = models.CharField(max_length=20)


class LegacyArticleTranslation(models.Model):
    master = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="legacy_rows")
    language_code = models.CharField(max_length=32)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
