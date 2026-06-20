from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.portfolios.views import AssetViewSet, PortfolioPositionViewSet, PortfolioViewSet

router = DefaultRouter()
router.register("assets", AssetViewSet, basename="asset")
router.register("portfolios", PortfolioViewSet, basename="portfolio")
router.register("positions", PortfolioPositionViewSet, basename="portfolio-position")

urlpatterns = [path("", include(router.urls))]
