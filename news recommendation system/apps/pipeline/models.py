from django.conf import settings
from django.db import models

from apps.core.models import TimestampedModel
from apps.portfolios.models import Portfolio


class PipelineJob(TimestampedModel):
    class JobType(models.TextChoices):
        INGEST = "ingest", "Ingest"
        RECOMMEND = "recommend", "Recommend"
        DIGEST = "digest", "Digest"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, null=True, blank=True)
    job_type = models.CharField(max_length=16, choices=JobType.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
