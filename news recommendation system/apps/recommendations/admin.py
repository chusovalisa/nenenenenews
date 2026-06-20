from django.contrib import admin

from apps.recommendations.models import RankedNews, RecommendationRun

admin.site.register(RecommendationRun)
admin.site.register(RankedNews)
