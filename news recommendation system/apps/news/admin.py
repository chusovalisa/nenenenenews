from django.contrib import admin

from apps.news.models import NewsArticle, NewsChunk, NewsEntity, NewsSource

admin.site.register(NewsSource)
admin.site.register(NewsArticle)
admin.site.register(NewsEntity)
admin.site.register(NewsChunk)
