from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portfolios', '0002_asset_user_scope'),
    ]

    operations = [
        migrations.AddField(
            model_name='asset',
            name='aliases',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
