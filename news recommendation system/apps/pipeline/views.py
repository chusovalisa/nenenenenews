from rest_framework import permissions, response, views, viewsets

from apps.pipeline.models import PipelineJob
from apps.pipeline.serializers import PipelineJobSerializer
from apps.pipeline.services import PipelineOrchestrator


class PipelineJobViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PipelineJobSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return PipelineJob.objects.filter(user=self.request.user)


class IngestAPIView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        result = PipelineOrchestrator().ingest_news(lookback_days=request.data.get("lookback_days"))
        return response.Response(result)


class BuildDigestAPIView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, portfolio_id: int):
        top_k = int(request.data.get("top_k", 5))
        refresh_raw = request.data.get("refresh_news", True)
        refresh_news = str(refresh_raw).strip().lower() not in {"0", "false", "no", "off"}
        result = PipelineOrchestrator().build_digest(
            user_id=request.user.id,
            portfolio_id=portfolio_id,
            top_k=top_k,
            refresh_news=refresh_news,
            lookback_days=request.data.get("lookback_days"),
        )
        return response.Response(result)
