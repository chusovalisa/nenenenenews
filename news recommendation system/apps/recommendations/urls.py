from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.recommendations.views import RecommendationRunViewSet, RunRecommendationAPIView

router = DefaultRouter()
router.register("runs", RecommendationRunViewSet, basename="recommendation-run")

urlpatterns = [
    path("", include(router.urls)),
    path("portfolio/<int:portfolio_id>/run/", RunRecommendationAPIView.as_view(), name="run-recommendation"),
]
