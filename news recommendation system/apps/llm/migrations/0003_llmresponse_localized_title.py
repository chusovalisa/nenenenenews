from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('llm', '0002_alter_llmclaim_status_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='llmresponse',
            name='localized_title',
            field=models.CharField(blank=True, max_length=600),
        ),
    ]
