import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='NewsArticle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('external_id', models.CharField(blank=True, max_length=255)),
                ('url', models.URLField(max_length=600, unique=True)),
                ('title', models.CharField(max_length=600)),
                ('summary', models.TextField(blank=True)),
                ('content', models.TextField()),
                ('language', models.CharField(default='en', max_length=16)),
                ('published_at', models.DateTimeField()),
                ('ingested_at', models.DateTimeField(auto_now_add=True)),
                ('content_hash', models.CharField(db_index=True, max_length=64)),
                ('metadata', models.JSONField(blank=True, default=dict)),
            ],
            options={
                'ordering': ['-published_at'],
            },
        ),
        migrations.CreateModel(
            name='NewsSource',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(max_length=128)),
                ('slug', models.SlugField(unique=True)),
                ('source_type', models.CharField(choices=[('rss', 'RSS'), ('api', 'API'), ('manual', 'Manual')], default='rss', max_length=16)),
                ('base_url', models.URLField(max_length=600)),
                ('reliability_score', models.FloatField(default=0.5)),
                ('is_trusted', models.BooleanField(default=False)),
                ('is_active', models.BooleanField(default=True)),
                ('config', models.JSONField(blank=True, default=dict)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='NewsEntity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('entity_type', models.CharField(choices=[('ticker', 'Ticker'), ('company', 'Company'), ('sector', 'Sector'), ('person', 'Person'), ('money', 'Money'), ('date', 'Date')], max_length=16)),
                ('text', models.CharField(max_length=255)),
                ('normalized', models.CharField(blank=True, max_length=255)),
                ('ticker', models.CharField(blank=True, max_length=32)),
                ('confidence', models.FloatField(default=0.5)),
                ('article', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='entities', to='news.newsarticle')),
            ],
            options={
                'ordering': ['article_id', 'entity_type', 'text'],
            },
        ),
        migrations.AddField(
            model_name='newsarticle',
            name='source',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='articles', to='news.newssource'),
        ),
        migrations.CreateModel(
            name='NewsChunk',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('chunk_index', models.PositiveIntegerField()),
                ('text', models.TextField()),
                ('embedding_model', models.CharField(max_length=128)),
                ('vector_id', models.CharField(blank=True, db_index=True, max_length=128)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('article', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chunks', to='news.newsarticle')),
            ],
            options={
                'ordering': ['article_id', 'chunk_index'],
                'unique_together': {('article', 'chunk_index', 'embedding_model')},
            },
        ),
        migrations.AddIndex(
            model_name='newsarticle',
            index=models.Index(fields=['published_at'], name='news_newsar_publish_df29a9_idx'),
        ),
        migrations.AddIndex(
            model_name='newsarticle',
            index=models.Index(fields=['language'], name='news_newsar_languag_e5c680_idx'),
        ),
        migrations.AddIndex(
            model_name='newsarticle',
            index=models.Index(fields=['content_hash'], name='news_newsar_content_e2a094_idx'),
        ),
    ]
