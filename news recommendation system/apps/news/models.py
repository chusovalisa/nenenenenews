from django.db import models

from apps.core.models import TimestampedModel


class NewsSource(TimestampedModel):
    class SourceType(models.TextChoices):
        RSS = "rss", "RSS"
        API = "api", "API"
        MANUAL = "manual", "Manual"

    name = models.CharField(max_length=128)
    slug = models.SlugField(unique=True)
    source_type = models.CharField(max_length=16, choices=SourceType.choices, default=SourceType.RSS)
    base_url = models.URLField(max_length=600)
    reliability_score = models.FloatField(default=0.5)
    is_trusted = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class NewsArticle(TimestampedModel):
    source = models.ForeignKey(NewsSource, on_delete=models.PROTECT, related_name="articles")
    external_id = models.CharField(max_length=255, blank=True)
    url = models.URLField(max_length=600, unique=True)
    title = models.CharField(max_length=600)
    summary = models.TextField(blank=True)
    content = models.TextField()
    language = models.CharField(max_length=16, default="en")
    published_at = models.DateTimeField()
    ingested_at = models.DateTimeField(auto_now_add=True)
    content_hash = models.CharField(max_length=64, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-published_at"]
        indexes = [
            models.Index(fields=["published_at"]),
            models.Index(fields=["language"]),
            models.Index(fields=["content_hash"]),
        ]

    def __str__(self) -> str:
        return self.title


class NewsEntity(TimestampedModel):
    class EntityType(models.TextChoices):
        TICKER = "ticker", "Ticker"
        COMPANY = "company", "Company"
        SECTOR = "sector", "Sector"
        PERSON = "person", "Person"
        MONEY = "money", "Money"
        DATE = "date", "Date"
        ISIN = "isin", "ISIN"

    article = models.ForeignKey(NewsArticle, on_delete=models.CASCADE, related_name="entities")
    entity_type = models.CharField(max_length=16, choices=EntityType.choices)
    text = models.CharField(max_length=255)
    normalized = models.CharField(max_length=255, blank=True)
    ticker = models.CharField(max_length=32, blank=True)
    confidence = models.FloatField(default=0.5)

    class Meta:
        ordering = ["article_id", "entity_type", "text"]


class NewsChunk(TimestampedModel):
    article = models.ForeignKey(NewsArticle, on_delete=models.CASCADE, related_name="chunks")
    chunk_index = models.PositiveIntegerField()
    text = models.TextField()
    embedding_model = models.CharField(max_length=128)
    vector_id = models.CharField(max_length=128, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ("article", "chunk_index", "embedding_model")
        ordering = ["article_id", "chunk_index"]
