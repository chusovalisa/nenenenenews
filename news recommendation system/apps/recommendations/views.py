from rest_framework import permissions, response, views, viewsets

from apps.portfolios.models import Portfolio
from apps.recommendations.models import RecommendationRun
from apps.recommendations.serializers import RecommendationRunSerializer
from apps.recommendations.services import PortfolioRecommender


class RecommendationRunViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RecommendationRunSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return RecommendationRun.objects.filter(user=self.request.user).prefetch_related("items__article")


class RunRecommendationAPIView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, portfolio_id: int):
        top_k = int(request.data.get("top_k", 10))
        lookback_days = request.data.get("lookback_days")
        portfolio = Portfolio.objects.get(id=portfolio_id, user=request.user)
        run = PortfolioRecommender().run(portfolio=portfolio, top_k=top_k, lookback_days=lookback_days)
        return response.Response(RecommendationRunSerializer(run).data)
