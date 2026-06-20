import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('llm', '0001_initial'),
        ('news', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='FactCheckResult',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('confirmed', 'Confirmed'), ('not_confirmed', 'Not confirmed'), ('insufficient_data', 'Insufficient data')], max_length=32)),
                ('confidence', models.FloatField(default=0.0)),
                ('explanation', models.TextField(blank=True)),
                ('evidence_count', models.PositiveIntegerField(default=0)),
                ('claim', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='fact_check', to='llm.llmclaim')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='Evidence',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('excerpt', models.TextField()),
                ('url', models.URLField(blank=True, max_length=600)),
                ('score', models.FloatField(default=0.0)),
                ('label', models.CharField(default='support', max_length=32)),
                ('article', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='news.newsarticle')),
                ('chunk', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='news.newschunk')),
                ('result', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='evidences', to='factcheck.factcheckresult')),
            ],
            options={
                'ordering': ['-score', 'id'],
            },
        ),
    ]
