from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.pipeline.views import BuildDigestAPIView, IngestAPIView, PipelineJobViewSet

router = DefaultRouter()
router.register("jobs", PipelineJobViewSet, basename="pipeline-job")

urlpatterns = [
    path("", include(router.urls)),
    path("ingest/", IngestAPIView.as_view(), name="pipeline-ingest"),
    path("portfolio/<int:portfolio_id>/digest/", BuildDigestAPIView.as_view(), name="pipeline-digest"),
]
