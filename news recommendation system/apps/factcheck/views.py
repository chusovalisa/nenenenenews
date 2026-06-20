from rest_framework import permissions, response, views, viewsets

from apps.factcheck.models import FactCheckResult
from apps.factcheck.serializers import FactCheckResultSerializer
from apps.factcheck.services import FactCheckService
from apps.llm.models import LLMResponse


class FactCheckResultViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = FactCheckResultSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return FactCheckResult.objects.filter(claim__response__user=self.request.user).prefetch_related("evidences")


class RunFactCheckAPIView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, response_id: int):
        LLMResponse.objects.get(id=response_id, user=request.user)
        results = FactCheckService().check_response_claims(response_id=response_id)
        return response.Response(FactCheckResultSerializer(results, many=True).data)
