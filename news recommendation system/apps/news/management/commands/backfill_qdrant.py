from django.core.management.base import BaseCommand

from apps.core.services import EmbeddingService, VectorStoreService
from apps.news.models import NewsChunk


class Command(BaseCommand):
    help = "Backfill existing news chunks into Qdrant"

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=128)

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        embedding = EmbeddingService()
        vector_store = VectorStoreService()
        qs = NewsChunk.objects.select_related("article", "article__source").order_by("id")
        total = qs.count()
        indexed = 0

        for start in range(0, total, batch_size):
            batch = list(qs[start : start + batch_size])
            texts = [chunk.text for chunk in batch]
            vectors = embedding.embed(texts)
            points = []
            for chunk, vector in zip(batch, vectors, strict=False):
                points.append(
                    {
                        "id": chunk.vector_id or f"{chunk.article_id}:{chunk.chunk_index}:{chunk.embedding_model}",
                        "vector": vector,
                        "payload": {
                            "article_id": chunk.article_id,
                            "chunk_index": chunk.chunk_index,
                            "source_slug": chunk.article.source.slug,
                            "title": chunk.article.title,
                            "url": chunk.article.url,
                            "published_at": chunk.article.published_at.isoformat(),
                            "language": chunk.article.language,
                            "is_trusted": chunk.article.source.is_trusted,
                        },
                    }
                )
            if points:
                vector_store.upsert(points=points, vector_size=len(vectors[0]))
                indexed += len(points)
                self.stdout.write(f"indexed {indexed}/{total}")

        self.stdout.write(self.style.SUCCESS(f"backfilled chunks: {indexed}"))
