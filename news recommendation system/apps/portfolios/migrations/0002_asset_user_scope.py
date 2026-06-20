from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def split_assets_by_user(apps, schema_editor):
    Asset = apps.get_model("portfolios", "Asset")
    Portfolio = apps.get_model("portfolios", "Portfolio")
    PortfolioPosition = apps.get_model("portfolios", "PortfolioPosition")

    for asset in Asset.objects.all().order_by("id"):
        user_ids = list(
            Portfolio.objects.filter(positions__asset=asset)
            .values_list("user_id", flat=True)
            .distinct()
        )
        if not user_ids:
            continue

        primary_user_id = user_ids[0]
        asset.user_id = primary_user_id
        asset.save(update_fields=["user"])

        for other_user_id in user_ids[1:]:
            cloned_asset = Asset.objects.create(
                user_id=other_user_id,
                symbol=asset.symbol,
                name=asset.name,
                asset_type=asset.asset_type,
                sector=asset.sector,
                exchange=asset.exchange,
            )
            PortfolioPosition.objects.filter(
                asset_id=asset.id,
                portfolio__user_id=other_user_id,
            ).update(asset_id=cloned_asset.id)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("portfolios", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="asset",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="assets",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="asset",
            name="symbol",
            field=models.CharField(max_length=32),
        ),
        migrations.RunPython(split_assets_by_user, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(
            name="asset",
            unique_together={("user", "symbol")},
        ),
    ]
