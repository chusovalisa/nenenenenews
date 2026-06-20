from rest_framework import permissions, response, viewsets
from rest_framework.decorators import action

from apps.news.models import NewsArticle, NewsSource
from apps.news.serializers import NewsArticleSerializer, NewsSourceSerializer
from apps.news.services import NewsIngestionService


class NewsSourceViewSet(viewsets.ModelViewSet):
    queryset = NewsSource.objects.all()
    serializer_class = NewsSourceSerializer

    def get_permissions(self):
        if self.action in {"list", "retrieve", "ingest"}:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]

    @action(detail=False, methods=["post"], url_path="ingest")
    def ingest(self, request):
        result = NewsIngestionService().ingest(lookback_days=request.data.get("lookback_days"))
        return response.Response(result)


class NewsArticleViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NewsArticleSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return NewsArticle.objects.select_related("source").prefetch_related("entities").all()
