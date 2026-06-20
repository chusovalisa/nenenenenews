import re

from apps.core.services import EmbeddingService, RuntimeConfigService
from apps.news.models import NewsArticle
from apps.portfolios.aliases import build_asset_aliases, build_contextual_asset_aliases, normalize_asset_text
from apps.recommendations.types import AssetMatcher


class RecommendationMatchingMixin:
    @staticmethod
    def _normalize_lookback_days(value: int | str | None) -> int:
        default = RuntimeConfigService.get("NEWS_LOOKBACK_DAYS", 1)
        try:
            return max(1, min(int(value or default), 365))
        except (TypeError, ValueError):
            return max(1, int(default))

    @staticmethod
    def _normalize_text(value: str) -> str:
        return normalize_asset_text(value)

    @classmethod
    def _build_matcher(
        cls,
        symbol: str,
        name: str,
        asset_type: str,
        exchange: str = "",
        aliases: list[str] | None = None,
        sector: str = "",
    ) -> AssetMatcher:
        built_aliases = build_asset_aliases(symbol=symbol, name=name, exchange=exchange, aliases=aliases)
        contextual_aliases = build_contextual_asset_aliases(symbol=symbol, name=name, aliases=aliases)
        return AssetMatcher(
            symbol=symbol.upper(),
            name=name,
            aliases=built_aliases,
            contextual_aliases=contextual_aliases,
            asset_type=asset_type,
            sector=sector,
            exchange=exchange,
        )

    @classmethod
    def _text_has_alias(cls, text: str, matcher: AssetMatcher) -> bool:
        normalized = f" {cls._normalize_text(text)} "
        symbol_token = matcher.symbol.lower()
        if f" {symbol_token} " in normalized:
            return True
        return any(f" {alias} " in normalized for alias in matcher.aliases if alias and alias != matcher.symbol)

    @classmethod
    def _text_has_company_alias(cls, text: str, matcher: AssetMatcher) -> bool:
        normalized = f" {cls._normalize_text(text)} "
        return any(f" {alias} " in normalized for alias in matcher.aliases if alias and alias != matcher.symbol)

    @classmethod
    def _text_has_contextual_alias(cls, text: str, matcher: AssetMatcher) -> bool:
        normalized = f" {cls._normalize_text(text)} "
        return any(f" {alias} " in normalized for alias in matcher.contextual_aliases)

    @classmethod
    def _context_windows(cls, text: str, alias: str) -> list[str]:
        normalized_words = cls._normalize_text(text).split()
        alias_words = alias.split()
        if not normalized_words or not alias_words:
            return []
        windows = []
        alias_len = len(alias_words)
        for idx in range(0, len(normalized_words) - alias_len + 1):
            if normalized_words[idx : idx + alias_len] != alias_words:
                continue
            start = max(0, idx - cls.CONTEXT_WINDOW_WORDS)
            end = min(len(normalized_words), idx + alias_len + cls.CONTEXT_WINDOW_WORDS)
            windows.append(" ".join(normalized_words[start:end]))
        return windows

    def _semantic_vector(self, text: str) -> list[float]:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        if not cleaned:
            return []
        if cleaned in self._semantic_cache:
            return self._semantic_cache[cleaned]
        if self._embedding_service is None:
            self._embedding_service = EmbeddingService()
        vectors = self._embedding_service.embed([cleaned])
        vector = vectors[0] if vectors and not self._embedding_service.is_fallback else []
        self._semantic_cache[cleaned] = vector
        return vector

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        numerator = sum(a * b for a, b in zip(left, right, strict=False))
        left_norm = sum(a * a for a in left) ** 0.5
        right_norm = sum(b * b for b in right) ** 0.5
        if not left_norm or not right_norm:
            return 0.0
        return numerator / (left_norm * right_norm)

    def _asset_profile(self, matcher: AssetMatcher) -> str:
        aliases = " ".join(sorted(alias for alias in matcher.aliases if alias != matcher.symbol))
        contextual_aliases = " ".join(sorted(matcher.contextual_aliases))
        return " ".join(
            part
            for part in [
                matcher.symbol,
                matcher.name,
                aliases,
                contextual_aliases,
                matcher.asset_type,
                matcher.sector,
                matcher.exchange,
            ]
            if part
        )

    def _semantic_relevance(self, text: str, matcher: AssetMatcher) -> float:
        return self._cosine_similarity(self._semantic_vector(text), self._semantic_vector(self._asset_profile(matcher)))

    def _semantic_context_matches(self, window: str, matcher: AssetMatcher) -> bool:
        threshold = float(RuntimeConfigService.get("RECOMMENDATION_CONTEXT_SEMANTIC_THRESHOLD", 0.42))
        return self._semantic_relevance(window, matcher) >= threshold

    def _article_semantic_text(self, article: NewsArticle) -> str:
        return " ".join([article.title or "", article.summary or "", (article.content or "")[:2500]]).strip()

    def _semantic_article_candidates(
        self,
        matchers: list[AssetMatcher],
        limit_per_asset: int = 80,
    ) -> set[int]:
        article_ids: set[int] = set()
        if self._embedding_service is None:
            self._embedding_service = EmbeddingService()
        for matcher in matchers:
            vectors = self._embedding_service.embed([self._asset_profile(matcher)])
            if not vectors or self._embedding_service.is_fallback:
                continue
            for hit in self._vector_store.search(vectors[0], limit=limit_per_asset):
                payload = hit.get("payload") or {}
                article_id = payload.get("article_id")
                if article_id:
                    article_ids.add(int(article_id))
        return article_ids

    def _contextual_alias_matches(self, text: str, matcher: AssetMatcher) -> bool:
        for alias in matcher.contextual_aliases:
            for window in self._context_windows(text, alias):
                if matcher.symbol.lower() in set(window.split()):
                    return True
                if self._semantic_context_matches(window, matcher):
                    return True
        return False

