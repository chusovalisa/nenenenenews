import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('news', '0001_initial'),
        ('portfolios', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LLMProvider',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(max_length=128, unique=True)),
                ('provider_type', models.CharField(choices=[('openai', 'OpenAI'), ('huggingface', 'HuggingFace'), ('local', 'Local')], default='local', max_length=32)),
                ('model_name', models.CharField(max_length=128)),
                ('config', models.JSONField(blank=True, default=dict)),
                ('is_active', models.BooleanField(default=False)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='LLMResponse',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('prompt_version', models.CharField(default='v1', max_length=32)),
                ('model_name', models.CharField(blank=True, max_length=128)),
                ('input_payload', models.JSONField(blank=True, default=dict)),
                ('raw_text', models.TextField()),
                ('summary', models.TextField(blank=True)),
                ('impact_analysis', models.TextField(blank=True)),
                ('token_usage', models.JSONField(blank=True, default=dict)),
                ('article', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='llm_responses', to='news.newsarticle')),
                ('portfolio', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='llm_responses', to='portfolios.portfolio')),
                ('provider', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='llm.llmprovider')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='llm_responses', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='LLMClaim',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('claim_text', models.TextField()),
                ('claim_type', models.CharField(choices=[('event', 'Event'), ('numeric', 'Numeric'), ('date', 'Date'), ('corporate', 'Corporate'), ('other', 'Other')], default='other', max_length=16)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('confirmed', 'Confirmed'), ('not_confirmed', 'Not confirmed'), ('insufficient_data', 'Insufficient data')], default='pending', max_length=32)),
                ('extracted_data', models.JSONField(blank=True, default=dict)),
                ('response', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='claims', to='llm.llmresponse')),
            ],
            options={
                'ordering': ['response_id', 'id'],
            },
        ),
    ]
