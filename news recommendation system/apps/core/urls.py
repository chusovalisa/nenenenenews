from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.core.views import SystemConfigViewSet

router = DefaultRouter()
router.register("configs", SystemConfigViewSet, basename="system-config")

urlpatterns = [path("", include(router.urls))]
