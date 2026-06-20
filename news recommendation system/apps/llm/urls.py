from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.llm.views import LLMProviderViewSet, LLMResponseViewSet, SummarizeArticleAPIView

router = DefaultRouter()
router.register("providers", LLMProviderViewSet, basename="llm-provider")
router.register("responses", LLMResponseViewSet, basename="llm-response")

urlpatterns = [
    path("", include(router.urls)),
    path("articles/<int:article_id>/summarize/", SummarizeArticleAPIView.as_view(), name="summarize-article"),
]
