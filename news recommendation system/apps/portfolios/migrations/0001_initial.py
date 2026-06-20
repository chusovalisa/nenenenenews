import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Asset',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('symbol', models.CharField(max_length=32, unique=True)),
                ('name', models.CharField(max_length=255)),
                ('asset_type', models.CharField(choices=[('stock', 'Stock'), ('etf', 'ETF'), ('bond', 'Bond'), ('crypto', 'Crypto'), ('currency', 'Currency'), ('other', 'Other')], default='stock', max_length=16)),
                ('sector', models.CharField(blank=True, max_length=128)),
                ('exchange', models.CharField(blank=True, max_length=32)),
            ],
            options={
                'ordering': ['symbol'],
            },
        ),
        migrations.CreateModel(
            name='Portfolio',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(max_length=128)),
                ('base_currency', models.CharField(default='USD', max_length=8)),
                ('risk_profile', models.CharField(default='moderate', max_length=32)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='portfolios', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['name'],
                'unique_together': {('user', 'name')},
            },
        ),
        migrations.CreateModel(
            name='PortfolioPosition',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('quantity', models.DecimalField(decimal_places=6, max_digits=20)),
                ('average_price', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('weight_override', models.FloatField(blank=True, null=True)),
                ('asset', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='positions', to='portfolios.asset')),
                ('portfolio', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='positions', to='portfolios.portfolio')),
            ],
            options={
                'ordering': ['portfolio', 'asset__symbol'],
                'unique_together': {('portfolio', 'asset')},
            },
        ),
    ]
