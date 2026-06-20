from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.core.services import EmbeddingService, RuntimeConfigService, VectorStoreService
from apps.news.models import NewsArticle, NewsEntity
from apps.portfolios.models import Portfolio
from apps.recommendations.matching import RecommendationMatchingMixin
from apps.recommendations.models import RankedNews, RecommendationRun
from apps.recommendations.scoring import RecommendationScoringMixin
from apps.recommendations.selection import RecommendationSelectionMixin
from apps.recommendations.types import AssetMatcher, ScoredArticle


class PortfolioRecommender(RecommendationMatchingMixin, RecommendationSelectionMixin, RecommendationScoringMixin):
    CONTEXT_WINDOW_WORDS = 10

    def __init__(self) -> None:
        self._embedding_service: EmbeddingService | None = None
        self._vector_store = VectorStoreService()
        self._semantic_cache: dict[str, list[float]] = {}

    def run(self, portfolio: Portfolio, top_k: int = 10, lookback_days: int | None = None) -> RecommendationRun:
        weights = RuntimeConfigService.get(
            "SCORING_WEIGHTS",
            {"asset_overlap": 0.6, "source_reliability": 0.25, "freshness": 0.15},
        )
        allow_duplicate_symbols = bool(RuntimeConfigService.get("ALLOW_DUPLICATE_SYMBOL_NEWS", False))
        lookback_days = self._normalize_lookback_days(lookback_days)
        fallback_lookback_days = max(
            lookback_days,
            int(RuntimeConfigService.get("NEWS_FALLBACK_LOOKBACK_DAYS", lookback_days)),
        )
        run = RecommendationRun.objects.create(
            user=portfolio.user,
            portfolio=portfolio,
            status=RecommendationRun.Status.RUNNING,
            config_snapshot={
                "weights": weights,
                "top_k": top_k,
                "allow_duplicate_symbols": allow_duplicate_symbols,
                "lookback_days": lookback_days,
                "fallback_lookback_days": fallback_lookback_days,
            },
        )
        positions = list(portfolio.positions.select_related("asset"))
        matchers = [
            self._build_matcher(
                p.asset.symbol,
                p.asset.name,
                p.asset.asset_type,
                p.asset.exchange,
                p.asset.aliases,
                sector=p.asset.sector,
            )
            for p in positions
        ]
        symbols = {matcher.symbol for matcher in matchers}
        recent_limit = timezone.now() - timedelta(days=lookback_days)
        fallback_limit = timezone.now() - timedelta(days=fallback_lookback_days)
        articles_qs = (
            NewsArticle.objects.filter(published_at__gte=recent_limit, source__is_active=True)
            .select_related("source")
            .prefetch_related("entities")
        )
        if symbols:
            semantic_article_ids = self._semantic_article_candidates(matchers)
            query = Q(entities__entity_type=NewsEntity.EntityType.TICKER, entities__ticker__in=symbols)
            for matcher in matchers:
                for alias in matcher.aliases:
                    if alias == matcher.symbol or len(alias) < 3:
                        continue
                    query |= Q(title__icontains=alias) | Q(content__icontains=alias)
                for alias in matcher.contextual_aliases:
                    if len(alias) < 3:
                        continue
                    query |= Q(title__icontains=alias) | Q(content__icontains=alias)
            if semantic_article_ids:
                query |= Q(id__in=semantic_article_ids)
            articles_qs = articles_qs.filter(query).distinct()
        else:
            articles_qs = articles_qs.none()

        articles = articles_qs
        scored: list[ScoredArticle] = []
        for article in articles:
            scored_article = self._score_article(
                article=article,
                matchers=matchers,
                symbols=symbols,
                weights=weights,
            )
            if scored_article:
                scored.append(scored_article)

        covered_symbols = {
            symbol
            for item in scored
            for symbol in item.breakdown.get("matched_symbols", [])
        }
        missing_matchers = [matcher for matcher in matchers if matcher.symbol not in covered_symbols]
        if missing_matchers and fallback_limit < recent_limit:
            fallback_qs = (
                NewsArticle.objects.filter(published_at__gte=fallback_limit, published_at__lt=recent_limit)
                .select_related("source")
                .prefetch_related("entities")
                .order_by("-published_at")
            )
            for matcher in missing_matchers:
                best_fallback: ScoredArticle | None = None
                for article in fallback_qs:
                    if not self._article_matches_asset(article, matcher):
                        continue
                    scored_article = self._score_article(
                        article=article,
                        matchers=[matcher],
                        symbols={matcher.symbol},
                        weights=weights,
                        freshness_multiplier=0.35,
                    )
                    if not scored_article:
                        continue
                    if best_fallback is None or scored_article.score > best_fallback.score:
                        best_fallback = scored_article
                if best_fallback:
                    scored.append(best_fallback)

        ranked = self._select_diverse_top(scored=scored, top_k=top_k, allow_duplicate_symbols=allow_duplicate_symbols)
        RankedNews.objects.bulk_create(
            [
                RankedNews(run=run, article=item.article, rank=idx + 1, score=item.score, score_breakdown=item.breakdown)
                for idx, item in enumerate(ranked)
            ]
        )
        run.status = RecommendationRun.Status.DONE
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "completed_at", "updated_at"])
        return run
