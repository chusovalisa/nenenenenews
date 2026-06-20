from django.conf import settings
from django.db import models

from apps.core.models import TimestampedModel
from apps.news.models import NewsArticle
from apps.portfolios.models import Portfolio


class LLMProvider(TimestampedModel):
    class ProviderType(models.TextChoices):
        OPENAI = "openai", "OpenAI"
        HF = "huggingface", "HuggingFace"
        OLLAMA = "ollama", "Ollama"
        LOCAL = "local", "Local"

    name = models.CharField(max_length=128, unique=True)
    provider_type = models.CharField(max_length=32, choices=ProviderType.choices, default=ProviderType.LOCAL)
    model_name = models.CharField(max_length=128)
    config = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]


class LLMResponse(TimestampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="llm_responses")
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="llm_responses")
    article = models.ForeignKey(NewsArticle, on_delete=models.CASCADE, related_name="llm_responses")
    provider = models.ForeignKey(LLMProvider, on_delete=models.SET_NULL, null=True, blank=True)
    prompt_version = models.CharField(max_length=32, default="v1")
    model_name = models.CharField(max_length=128, blank=True)
    input_payload = models.JSONField(default=dict, blank=True)
    raw_text = models.TextField()
    localized_title = models.CharField(max_length=600, blank=True)
    summary = models.TextField(blank=True)
    impact_analysis = models.TextField(blank=True)
    token_usage = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]


class LLMClaim(TimestampedModel):
    class ClaimType(models.TextChoices):
        EVENT = "event", "Event"
        NUMERIC = "numeric", "Numeric"
        DATE = "date", "Date"
        CORPORATE = "corporate", "Corporate"
        OTHER = "other", "Other"

    class VerificationStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        CONTRADICTED = "contradicted", "Contradicted"
        NOT_CONFIRMED = "not_confirmed", "Not confirmed"
        INSUFFICIENT = "insufficient_data", "Insufficient data"

    response = models.ForeignKey(LLMResponse, on_delete=models.CASCADE, related_name="claims")
    claim_text = models.TextField()
    claim_type = models.CharField(max_length=16, choices=ClaimType.choices, default=ClaimType.OTHER)
    status = models.CharField(max_length=32, choices=VerificationStatus.choices, default=VerificationStatus.PENDING)
    extracted_data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["response_id", "id"]
