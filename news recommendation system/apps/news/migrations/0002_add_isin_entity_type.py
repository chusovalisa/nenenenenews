from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("news", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="newsentity",
            name="entity_type",
            field=models.CharField(
                choices=[
                    ("ticker", "Ticker"),
                    ("company", "Company"),
                    ("sector", "Sector"),
                    ("person", "Person"),
                    ("money", "Money"),
                    ("date", "Date"),
                    ("isin", "ISIN"),
                ],
                max_length=16,
            ),
        ),
    ]
