from rest_framework import permissions, response, views, viewsets

from apps.llm.models import LLMProvider, LLMResponse
from apps.llm.serializers import LLMProviderSerializer, LLMResponseSerializer
from apps.llm.services import LLMService
from apps.news.models import NewsArticle
from apps.portfolios.models import Portfolio


class LLMProviderViewSet(viewsets.ModelViewSet):
    queryset = LLMProvider.objects.all()
    serializer_class = LLMProviderSerializer
    permission_classes = [permissions.IsAdminUser]


class LLMResponseViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LLMResponseSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return LLMResponse.objects.filter(user=self.request.user).prefetch_related("claims")


class SummarizeArticleAPIView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, article_id: int):
        portfolio = Portfolio.objects.get(id=request.data["portfolio_id"], user=request.user)
        article = NewsArticle.objects.get(id=article_id)
        llm_response = LLMService().summarize_article(user=request.user, portfolio=portfolio, article=article)
        return response.Response(LLMResponseSerializer(llm_response).data)
