from django.db import models

from apps.core.models import TimestampedModel
from apps.llm.models import LLMClaim
from apps.news.models import NewsArticle, NewsChunk


class FactCheckResult(TimestampedModel):
    claim = models.OneToOneField(LLMClaim, on_delete=models.CASCADE, related_name="fact_check")
    status = models.CharField(max_length=32, choices=LLMClaim.VerificationStatus.choices)
    confidence = models.FloatField(default=0.0)
    explanation = models.TextField(blank=True)
    evidence_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]


class Evidence(TimestampedModel):
    result = models.ForeignKey(FactCheckResult, on_delete=models.CASCADE, related_name="evidences")
    article = models.ForeignKey(NewsArticle, on_delete=models.SET_NULL, null=True, blank=True)
    chunk = models.ForeignKey(NewsChunk, on_delete=models.SET_NULL, null=True, blank=True)
    excerpt = models.TextField()
    url = models.URLField(max_length=600, blank=True)
    score = models.FloatField(default=0.0)
    label = models.CharField(max_length=32, default="support")

    class Meta:
        ordering = ["-score", "id"]
