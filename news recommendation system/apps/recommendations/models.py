from django.conf import settings
from django.db import models

from apps.core.models import TimestampedModel
from apps.news.models import NewsArticle
from apps.portfolios.models import Portfolio


class RecommendationRun(TimestampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recommendation_runs")
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="recommendation_runs")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    config_snapshot = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class RankedNews(TimestampedModel):
    run = models.ForeignKey(RecommendationRun, on_delete=models.CASCADE, related_name="items")
    article = models.ForeignKey(NewsArticle, on_delete=models.CASCADE, related_name="rankings")
    rank = models.PositiveIntegerField()
    score = models.FloatField()
    score_breakdown = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ("run", "article")
        ordering = ["run_id", "rank"]
