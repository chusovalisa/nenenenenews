from rest_framework import permissions, viewsets

from apps.portfolios.models import Asset, Portfolio, PortfolioPosition
from apps.portfolios.serializers import AssetSerializer, PortfolioPositionSerializer, PortfolioSerializer


class AuthenticatedViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]


class AssetViewSet(AuthenticatedViewSet):
    serializer_class = AssetSerializer

    def get_queryset(self):
        return Asset.objects.filter(user=self.request.user).order_by("symbol")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class PortfolioViewSet(AuthenticatedViewSet):
    serializer_class = PortfolioSerializer

    def get_queryset(self):
        return Portfolio.objects.filter(user=self.request.user).prefetch_related("positions__asset")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class PortfolioPositionViewSet(AuthenticatedViewSet):
    serializer_class = PortfolioPositionSerializer

    def get_queryset(self):
        return PortfolioPosition.objects.filter(portfolio__user=self.request.user).select_related("asset", "portfolio")
