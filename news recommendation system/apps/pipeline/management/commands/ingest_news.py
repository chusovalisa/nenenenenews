from django.core.management.base import BaseCommand

from apps.pipeline.services import PipelineOrchestrator


class Command(BaseCommand):
    help = "Ingest news from configured sources"

    def add_arguments(self, parser):
        parser.add_argument("--lookback-days", type=int, default=1)

    def handle(self, *args, **options):
        result = PipelineOrchestrator().ingest_news(lookback_days=options["lookback_days"])
        self.stdout.write(self.style.SUCCESS(str(result)))
