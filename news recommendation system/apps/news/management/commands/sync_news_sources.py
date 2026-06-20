from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core.services import RuntimeConfigService
from apps.news.models import NewsSource
from apps.news.source_presets import OFFICIAL_RU_NEWS_SOURCES


class Command(BaseCommand):
    help = "Sync configured news sources into the database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--preset",
            choices=["official_ru"],
            default="official_ru",
            help="Preset of sources to sync",
        )
        parser.add_argument(
            "--from-env",
            action="store_true",
            help="Use NEWS_SOURCES from runtime config or Django settings instead of the preset",
        )
        parser.add_argument(
            "--deactivate-missing",
            action="store_true",
            help="Deactivate DB sources that are not present in the synced list",
        )

    def handle(self, *args, **options):
        if options["from_env"]:
            source_dicts = RuntimeConfigService.get("NEWS_SOURCES", getattr(settings, "NEWS_SOURCES", []))
        elif options["preset"] == "official_ru":
            source_dicts = OFFICIAL_RU_NEWS_SOURCES
        else:
            source_dicts = []

        synced_slugs: list[str] = []
        for source_data in source_dicts:
            slug = source_data["slug"]
            synced_slugs.append(slug)
            source, created = NewsSource.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": source_data["name"],
                    "source_type": source_data.get("source_type", NewsSource.SourceType.RSS),
                    "base_url": source_data["base_url"],
                    "is_trusted": source_data.get("is_trusted", False),
                    "is_active": source_data.get("is_active", True),
                    "reliability_score": source_data.get("reliability_score", 0.5),
                    "config": source_data.get("config", {}),
                },
            )
            action = "created" if created else "updated"
            self.stdout.write(f"{action}: {source.slug} -> {source.base_url}")

        if options["deactivate_missing"] and synced_slugs:
            deactivated = NewsSource.objects.exclude(slug__in=synced_slugs).update(is_active=False)
            self.stdout.write(f"deactivated: {deactivated}")

        self.stdout.write(self.style.SUCCESS(f"synced sources: {len(synced_slugs)}"))
