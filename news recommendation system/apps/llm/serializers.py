from rest_framework import serializers

from apps.llm.models import LLMClaim, LLMProvider, LLMResponse


class LLMProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model = LLMProvider
        fields = "__all__"


class LLMClaimSerializer(serializers.ModelSerializer):
    class Meta:
        model = LLMClaim
        fields = "__all__"


class LLMResponseSerializer(serializers.ModelSerializer):
    claims = LLMClaimSerializer(many=True, read_only=True)

    class Meta:
        model = LLMResponse
        fields = "__all__"
