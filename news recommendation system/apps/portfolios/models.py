from django.conf import settings
from django.db import models

from apps.core.models import TimestampedModel


class Asset(TimestampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assets",
        null=True,
        blank=True,
    )

    class AssetType(models.TextChoices):
        STOCK = "stock", "Stock"
        ETF = "etf", "ETF"
        BOND = "bond", "Bond"
        CRYPTO = "crypto", "Crypto"
        CURRENCY = "currency", "Currency"
        OTHER = "other", "Other"

    symbol = models.CharField(max_length=32)
    name = models.CharField(max_length=255)
    aliases = models.JSONField(default=list, blank=True)
    asset_type = models.CharField(max_length=16, choices=AssetType.choices, default=AssetType.STOCK)
    sector = models.CharField(max_length=128, blank=True)
    exchange = models.CharField(max_length=32, blank=True)

    class Meta:
        unique_together = ("user", "symbol")
        ordering = ["symbol"]

    def __str__(self) -> str:
        return self.symbol


class Portfolio(TimestampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="portfolios")
    name = models.CharField(max_length=128)
    base_currency = models.CharField(max_length=8, default="USD")
    risk_profile = models.CharField(max_length=32, default="moderate")

    class Meta:
        unique_together = ("user", "name")
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.name}"


class PortfolioPosition(TimestampedModel):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="positions")
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="positions")
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    average_price = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    weight_override = models.FloatField(null=True, blank=True)

    class Meta:
        unique_together = ("portfolio", "asset")
        ordering = ["portfolio", "asset__symbol"]

    def __str__(self) -> str:
        return f"{self.portfolio_id}:{self.asset.symbol}"
