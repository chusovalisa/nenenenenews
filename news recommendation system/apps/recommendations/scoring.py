from django.utils import timezone

from apps.core.services import RuntimeConfigService
from apps.news.models import NewsArticle, NewsEntity
from apps.portfolios.models import Asset
from apps.recommendations.types import AssetMatcher, ScoredArticle


class RecommendationScoringMixin:
    def _article_match_score(self, article: NewsArticle, matcher: AssetMatcher) -> tuple[float, dict]:
        entities = list(article.entities.all())
        article_symbols = {entity.ticker.upper() for entity in entities if entity.ticker}
        company_entities = {
            (entity.normalized or "").strip().lower()
            for entity in entities
            if entity.entity_type == NewsEntity.EntityType.COMPANY and (entity.normalized or "").strip()
        }
        company_entity_match = bool(company_entities.intersection(matcher.aliases))
        article_text = self._article_semantic_text(article)
        title_summary = f"{article.title} {article.summary or ''}"
        title_match = self._text_has_alias(article.title, matcher)
        summary_match = self._text_has_alias(article.summary or "", matcher)
        body_match = self._text_has_alias(article.content[:1500], matcher)
        company_match = self._text_has_company_alias(article_text, matcher)
        contextual_match = self._contextual_alias_matches(title_summary, matcher) or self._contextual_alias_matches(article.content[:1500], matcher)
        semantic_score = self._semantic_relevance(article_text, matcher)

        ticker_score = 1.0 if matcher.symbol in article_symbols or title_match else 0.0
        alias_score = 0.85 if summary_match or body_match or company_match else 0.0
        contextual_score = 0.7 if contextual_match else 0.0
        semantic_threshold = float(RuntimeConfigService.get("RECOMMENDATION_SEMANTIC_THRESHOLD", 0.5))
        semantic_only_threshold = float(RuntimeConfigService.get("RECOMMENDATION_SEMANTIC_ONLY_THRESHOLD", 0.62))

        if self._is_technical_source(article) and matcher.asset_type == Asset.AssetType.STOCK and not (title_match or summary_match or ticker_score):
            semantic_score *= 0.5
        if (
            matcher.asset_type == Asset.AssetType.STOCK
            and company_entities
            and not company_entity_match
            and matcher.symbol not in article_symbols
            and not (title_match or summary_match or body_match or company_match or contextual_match)
        ):
            semantic_score = 0.0

        has_lexical_signal = bool(ticker_score or alias_score or contextual_score)
        if matcher.asset_type == Asset.AssetType.STOCK and not has_lexical_signal:
            semantic_score = 0.0

        score = max(ticker_score, alias_score, contextual_score, semantic_score)
        if not has_lexical_signal and semantic_score < semantic_only_threshold:
            score = 0.0
        elif has_lexical_signal and score < semantic_threshold:
            score = max(score, semantic_threshold)

        if matcher.symbol in article_symbols and len(article_symbols) == 1 and len(company_entities) <= 2:
            score = max(score, 0.95)

        return round(float(min(1.0, score)), 6), {
            "ticker_entity": matcher.symbol in article_symbols,
            "title_match": title_match,
            "summary_match": summary_match,
            "body_match": body_match,
            "company_match": company_match,
            "contextual_match": contextual_match,
            "semantic_relevance": round(float(semantic_score), 6),
        }

    def _article_matches_asset(self, article: NewsArticle, matcher: AssetMatcher) -> bool:
        score, _ = self._article_match_score(article, matcher)
        return score > 0

    @staticmethod
    def _is_technical_source(article: NewsArticle) -> bool:
        return bool((article.source.config or {}).get("technical_feed"))


    def _score_article(
        self,
        article: NewsArticle,
        matchers: list[AssetMatcher],
        symbols: set[str],
        weights: dict,
        freshness_multiplier: float = 1.0,
    ) -> ScoredArticle | None:
        match_results = []
        for matcher in matchers:
            relevance, signals = self._article_match_score(article, matcher)
            if relevance > 0:
                match_results.append((matcher, relevance, signals))
        matched_symbols = sorted(matcher.symbol for matcher, _, _ in match_results)
        overlap = (sum(relevance for _, relevance, _ in match_results) / max(len(symbols), 1)) if symbols else 0.0
        if overlap <= 0:
            return None
        reliability = article.source.reliability_score
        age_hours = max((timezone.now() - article.published_at).total_seconds() / 3600, 1)
        freshness = (1.0 / age_hours) * freshness_multiplier
        score = (
            weights.get("asset_overlap", 0.6) * overlap
            + weights.get("source_reliability", 0.25) * reliability
            + weights.get("freshness", 0.15) * freshness
        )
        return ScoredArticle(
            article=article,
            score=round(float(score), 6),
            breakdown={
                "asset_overlap": round(float(overlap), 6),
                "matched_symbols": matched_symbols,
                "portfolio_relevance": [
                    {
                        "symbol": matcher.symbol,
                        "reason": self._asset_relevance_reason(article, matcher),
                        "relevance": relevance,
                        "signals": signals,
                    }
                    for matcher, relevance, signals in match_results
                ],
                "source_reliability": round(float(reliability), 6),
                "freshness": round(float(freshness), 6),
                "fallback_window": freshness_multiplier < 1.0,
            },
        )

