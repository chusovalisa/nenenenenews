from django.core.management.base import BaseCommand, CommandError

from apps.pipeline.services import PipelineOrchestrator


class Command(BaseCommand):
    help = "Build portfolio digest with recommendation, LLM summary, and fact-check"

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--portfolio-id", type=int, required=True)
        parser.add_argument("--top-k", type=int, default=5)
        parser.add_argument("--lookback-days", type=int, default=1)
        parser.add_argument("--no-refresh-news", action="store_true")

    def handle(self, *args, **options):
        try:
            payload = PipelineOrchestrator().build_digest(
                user_id=options["user_id"],
                portfolio_id=options["portfolio_id"],
                top_k=options["top_k"],
                lookback_days=options["lookback_days"],
                refresh_news=not options["no_refresh_news"],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(str(payload)))
