from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.news.views import NewsArticleViewSet, NewsSourceViewSet

router = DefaultRouter()
router.register("sources", NewsSourceViewSet, basename="news-source")
router.register("articles", NewsArticleViewSet, basename="news-article")

urlpatterns = [path("", include(router.urls))]
