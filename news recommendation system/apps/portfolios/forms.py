from django import forms

from apps.portfolios.models import Asset, Portfolio, PortfolioPosition


class AssetForm(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def validate_unique(self):
        return

    def clean_symbol(self):
        symbol = (self.cleaned_data.get("symbol") or "").strip().upper()
        return symbol

    class Meta:
        model = Asset
        fields = ["symbol", "name"]
        labels = {
            "symbol": "Тикер",
            "name": "Название актива",
        }
        help_texts = {
            "symbol": "Например: SBER, GAZP, LKOH, AAPL",
            "name": "Полное или короткое название компании/инструмента",
        }


class PortfolioForm(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            return name
        if self.user and Portfolio.objects.filter(user=self.user, name__iexact=name).exists():
            raise forms.ValidationError("Портфель с таким названием у вас уже есть.")
        return name

    class Meta:
        model = Portfolio
        fields = ["name", "base_currency", "risk_profile"]
        labels = {
            "name": "Название портфеля",
            "base_currency": "Базовая валюта",
            "risk_profile": "Профиль риска",
        }


class PortfolioPositionForm(forms.ModelForm):
    def __init__(self, *args, portfolio=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.portfolio = portfolio
        self.user = user or (portfolio.user if portfolio else None)
        queryset = Asset.objects.order_by("symbol")
        if self.user:
            queryset = queryset.filter(user=self.user)
        else:
            queryset = queryset.none()
        self.fields["asset"].queryset = queryset
        self.fields["asset"].empty_label = "Сначала выберите актив"

    def clean_asset(self):
        asset = self.cleaned_data.get("asset")
        if (
            asset
            and self.portfolio
            and PortfolioPosition.objects.filter(portfolio=self.portfolio, asset=asset)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            raise forms.ValidationError("Этот актив уже добавлен в портфель.")
        return asset

    class Meta:
        model = PortfolioPosition
        fields = ["asset"]
        labels = {
            "asset": "Актив",
        }
