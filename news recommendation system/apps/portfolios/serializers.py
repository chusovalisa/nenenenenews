from rest_framework import serializers

from apps.portfolios.models import Asset, Portfolio, PortfolioPosition


class AssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = "__all__"
        read_only_fields = ["user"]


class PortfolioPositionSerializer(serializers.ModelSerializer):
    asset_symbol = serializers.CharField(source="asset.symbol", read_only=True)

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        portfolio = attrs.get("portfolio") or getattr(self.instance, "portfolio", None)
        asset = attrs.get("asset") or getattr(self.instance, "asset", None)
        if user and portfolio and portfolio.user_id != user.id:
            raise serializers.ValidationError("Нельзя изменить позицию чужого портфеля.")
        if user and asset and asset.user_id != user.id:
            raise serializers.ValidationError("Нельзя добавить чужой актив в портфель.")
        return attrs

    class Meta:
        model = PortfolioPosition
        fields = [
            "id",
            "portfolio",
            "asset",
            "asset_symbol",
            "quantity",
            "average_price",
            "weight_override",
            "created_at",
            "updated_at",
        ]


class PortfolioSerializer(serializers.ModelSerializer):
    positions = PortfolioPositionSerializer(many=True, read_only=True)

    class Meta:
        model = Portfolio
        fields = [
            "id",
            "user",
            "name",
            "base_currency",
            "risk_profile",
            "positions",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["user"]
