from rest_framework import serializers

from apps.news.models import NewsArticle, NewsChunk, NewsEntity, NewsSource


class NewsSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsSource
        fields = "__all__"


class NewsEntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsEntity
        fields = "__all__"


class NewsChunkSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsChunk
        fields = "__all__"


class NewsArticleSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source="source.name", read_only=True)
    entities = NewsEntitySerializer(many=True, read_only=True)

    class Meta:
        model = NewsArticle
        fields = [
            "id",
            "source",
            "source_name",
            "external_id",
            "url",
            "title",
            "summary",
            "content",
            "language",
            "published_at",
            "ingested_at",
            "metadata",
            "entities",
            "created_at",
            "updated_at",
        ]
