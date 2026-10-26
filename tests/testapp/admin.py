from django.contrib import admin

from py_translations.admin import TranslatableAdmin, TranslatableStackedInline

from .models import Article, Note, Page


class NoteInline(TranslatableStackedInline):
    model = Note
    extra = 0


@admin.register(Article)
class ArticleAdmin(TranslatableAdmin):
    inlines = [NoteInline]


@admin.register(Page)
class PageAdmin(TranslatableAdmin):
    pass
