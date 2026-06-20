from rest_framework import serializers

from apps.factcheck.models import Evidence, FactCheckResult


class EvidenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Evidence
        fields = "__all__"


class FactCheckResultSerializer(serializers.ModelSerializer):
    evidences = EvidenceSerializer(many=True, read_only=True)
    claim_text = serializers.CharField(source="claim.claim_text", read_only=True)

    class Meta:
        model = FactCheckResult
        fields = [
            "id",
            "claim",
            "claim_text",
            "status",
            "confidence",
            "explanation",
            "evidence_count",
            "evidences",
            "created_at",
            "updated_at",
        ]
