from rest_framework import serializers

from apps.recommendations.models import RankedNews, RecommendationRun


class RankedNewsSerializer(serializers.ModelSerializer):
    title = serializers.CharField(source="article.title", read_only=True)
    url = serializers.CharField(source="article.url", read_only=True)

    class Meta:
        model = RankedNews
        fields = ["id", "article", "title", "url", "rank", "score", "score_breakdown", "created_at"]


class RecommendationRunSerializer(serializers.ModelSerializer):
    items = RankedNewsSerializer(many=True, read_only=True)

    class Meta:
        model = RecommendationRun
        fields = "__all__"
