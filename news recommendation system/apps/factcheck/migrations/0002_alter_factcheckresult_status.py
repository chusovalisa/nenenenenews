from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('factcheck', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='factcheckresult',
            name='status',
            field=models.CharField(choices=[('pending', 'Pending'), ('confirmed', 'Confirmed'), ('contradicted', 'Contradicted'), ('not_confirmed', 'Not confirmed'), ('insufficient_data', 'Insufficient data')], max_length=32),
        ),
    ]
