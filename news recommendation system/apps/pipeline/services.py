from dataclasses import asdict, dataclass

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.factcheck.services import FactCheckService
from apps.llm.services import LLMService
from apps.news.services import NewsIngestionService
from apps.pipeline.models import PipelineJob
from apps.portfolios.models import Portfolio
from apps.recommendations.services import PortfolioRecommender


@dataclass
class DigestItem:
    article_id: int
    title: str
    url: str
    matched_symbols: list[str]
    portfolio_relevance: list[dict]
    summary: str
    impact_analysis: str
    factcheck: list[dict]


class PipelineOrchestrator:
    @staticmethod
    def _normalize_lookback_days(value: int | str | None, default: int = 1) -> int:
        try:
            return max(1, min(int(value or default), 365))
        except (TypeError, ValueError):
            return default

    def ingest_news(self, lookback_days: int | str | None = None) -> dict:
        lookback_days = self._normalize_lookback_days(lookback_days)
        job = PipelineJob.objects.create(
            job_type=PipelineJob.JobType.INGEST,
            status=PipelineJob.Status.RUNNING,
            payload={"lookback_days": lookback_days},
        )
        try:
            result = NewsIngestionService().ingest(lookback_days=lookback_days)
            job.status = PipelineJob.Status.DONE
            job.result = result
            job.save(update_fields=["status", "result", "updated_at"])
            return result
        except Exception as exc:
            job.status = PipelineJob.Status.FAILED
            job.error_message = str(exc)
            job.save(update_fields=["status", "error_message", "updated_at"])
            raise

    def build_digest(
        self,
        user_id: int,
        portfolio_id: int,
        top_k: int = 5,
        refresh_news: bool = True,
        lookback_days: int | str | None = None,
    ) -> dict:
        lookback_days = self._normalize_lookback_days(lookback_days)
        User = get_user_model()
        user = User.objects.get(id=user_id)
        portfolio = Portfolio.objects.get(id=portfolio_id, user=user)
        job = PipelineJob.objects.create(
            user=user,
            portfolio=portfolio,
            job_type=PipelineJob.JobType.DIGEST,
            status=PipelineJob.Status.RUNNING,
            payload={"top_k": top_k, "refresh_news": refresh_news, "lookback_days": lookback_days},
        )

        recommender = PortfolioRecommender()
        llm_service = LLMService()
        factcheck_service = FactCheckService()

        try:
            ingest_result = NewsIngestionService().ingest(lookback_days=lookback_days) if refresh_news else None
            run = recommender.run(portfolio=portfolio, top_k=top_k, lookback_days=lookback_days)
            items: list[DigestItem] = []

            for ranked in run.items.select_related("article").all():
                matched_symbols = ranked.score_breakdown.get("matched_symbols", [])
                portfolio_relevance = ranked.score_breakdown.get("portfolio_relevance", [])
                llm_response = llm_service.summarize_article(
                    user=user,
                    portfolio=portfolio,
                    article=ranked.article,
                    matched_symbols=matched_symbols,
                )
                results = factcheck_service.check_response_claims(llm_response.id)
                items.append(
                    DigestItem(
                        article_id=ranked.article_id,
                        title=llm_response.localized_title or ranked.article.title,
                        url=ranked.article.url,
                        matched_symbols=matched_symbols,
                        portfolio_relevance=portfolio_relevance,
                        summary=llm_response.summary,
                        impact_analysis=llm_response.impact_analysis,
                        factcheck=[
                            {
                                "claim": res.claim.claim_text,
                                "status": res.status,
                                "confidence": res.confidence,
                                "explanation": res.explanation,
                                "evidence": [
                                    {"url": ranked.article.url, "excerpt": ev.excerpt, "score": ev.score, "label": ev.label}
                                    for ev in res.evidences.all()[:3]
                                ],
                            }
                            for res in results
                        ],
                    )
                )

            payload = {
                "generated_at": timezone.now().isoformat(),
                "portfolio_id": portfolio.id,
                "lookback_days": lookback_days,
                "news_refresh": ingest_result,
                "recommendation_run_id": run.id,
                "items": [asdict(item) for item in items],
            }
            job.status = PipelineJob.Status.DONE
            job.result = payload
            job.save(update_fields=["status", "result", "updated_at"])
            return payload
        except Exception as exc:
            job.status = PipelineJob.Status.FAILED
            job.error_message = str(exc)
            job.save(update_fields=["status", "error_message", "updated_at"])
            raise
