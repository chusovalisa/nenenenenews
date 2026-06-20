from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("", include("apps.core.ui_urls")),
    path("admin/", admin.site.urls),
    path("api/core/", include("apps.core.urls")),
    path("api/portfolios/", include("apps.portfolios.urls")),
    path("api/news/", include("apps.news.urls")),
    path("api/recommendations/", include("apps.recommendations.urls")),
    path("api/llm/", include("apps.llm.urls")),
    path("api/factcheck/", include("apps.factcheck.urls")),
    path("api/pipeline/", include("apps.pipeline.urls")),
]
