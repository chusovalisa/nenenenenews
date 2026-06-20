from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('llm', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='llmclaim',
            name='status',
            field=models.CharField(choices=[('pending', 'Pending'), ('confirmed', 'Confirmed'), ('contradicted', 'Contradicted'), ('not_confirmed', 'Not confirmed'), ('insufficient_data', 'Insufficient data')], default='pending', max_length=32),
        ),
        migrations.AlterField(
            model_name='llmprovider',
            name='provider_type',
            field=models.CharField(choices=[('openai', 'OpenAI'), ('huggingface', 'HuggingFace'), ('ollama', 'Ollama'), ('local', 'Local')], default='local', max_length=32),
        ),
    ]
