from django.core.management.base import BaseCommand

from apps.news.models import NewsArticle, NewsEntity
from apps.news.services import EntityExtractor


class Command(BaseCommand):
    help = "Re-extract news entities for existing articles using the current extractor."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=200)

    def handle(self, *args, **options):
        batch_size = max(1, options["batch_size"])
        extractor = EntityExtractor()
        article_ids = list(NewsArticle.objects.order_by("id").values_list("id", flat=True))
        total = len(article_ids)
        created = 0

        for index in range(0, total, batch_size):
            batch_ids = article_ids[index : index + batch_size]
            articles = list(NewsArticle.objects.filter(id__in=batch_ids).order_by("id"))
            NewsEntity.objects.filter(article_id__in=batch_ids).delete()
            new_entities = []
            for article in articles:
                new_entities.extend(extractor.extract(article))
            if new_entities:
                NewsEntity.objects.bulk_create(new_entities, batch_size=1000)
                created += len(new_entities)
            self.stdout.write(f"processed {min(index + batch_size, total)}/{total}")

        self.stdout.write(self.style.SUCCESS(f"re-extracted entities: {created}"))
