from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.factcheck.views import FactCheckResultViewSet, RunFactCheckAPIView

router = DefaultRouter()
router.register("results", FactCheckResultViewSet, basename="factcheck-result")

urlpatterns = [
    path("", include(router.urls)),
    path("responses/<int:response_id>/run/", RunFactCheckAPIView.as_view(), name="run-factcheck"),
]
