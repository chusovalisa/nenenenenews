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
            name='RecommendationRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('running', 'Running'), ('done', 'Done'), ('failed', 'Failed')], default='pending', max_length=16)),
                ('config_snapshot', models.JSONField(blank=True, default=dict)),
                ('error_message', models.TextField(blank=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('portfolio', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='recommendation_runs', to='portfolios.portfolio')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='recommendation_runs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='RankedNews',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('rank', models.PositiveIntegerField()),
                ('score', models.FloatField()),
                ('score_breakdown', models.JSONField(blank=True, default=dict)),
                ('article', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rankings', to='news.newsarticle')),
                ('run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='recommendations.recommendationrun')),
            ],
            options={
                'ordering': ['run_id', 'rank'],
                'unique_together': {('run', 'article')},
            },
        ),
    ]
