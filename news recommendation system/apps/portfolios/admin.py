from django.contrib import admin

from apps.portfolios.models import Asset, Portfolio, PortfolioPosition

admin.site.register(Asset)
admin.site.register(Portfolio)
admin.site.register(PortfolioPosition)
