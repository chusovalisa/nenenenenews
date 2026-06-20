from apps.news.models import NewsArticle
from apps.recommendations.types import ScoredArticle


class RecommendationSelectionMixin:
    @classmethod
    def _article_topic_key(cls, article: NewsArticle, matched_symbols: list[str]) -> str:
        title = cls._normalize_text(article.title)
        symbol_key = ",".join(sorted(matched_symbols))
        return f"{symbol_key}:{title[:120]}"

    def _asset_relevance_reason(self, article: NewsArticle, matcher: AssetMatcher) -> str:
        entities = list(article.entities.all())
        article_symbols = {entity.ticker.upper() for entity in entities if entity.ticker}
        if self._text_has_alias(article.title, matcher):
            return "тикер или эмитент прямо упомянут в заголовке"
        if self._text_has_alias(article.summary or "", matcher):
            return "тикер или эмитент прямо упомянут в описании"
        if matcher.symbol in article_symbols:
            return "тикер найден среди сущностей публикации"
        if self._text_has_company_alias(article.content[:1500], matcher):
            return "эмитент упомянут в тексте публикации"
        if self._contextual_alias_matches(f"{article.title} {article.summary} {article.content[:1500]}", matcher):
            return "название найдено в контексте компании или ценной бумаги"
        return "публикация совпала с профилем актива по тексту"

    @classmethod
    def _select_diverse_top(cls, scored: list[ScoredArticle], top_k: int, allow_duplicate_symbols: bool) -> list[ScoredArticle]:
        ordered = sorted(scored, key=lambda item: item.score, reverse=True)
        if allow_duplicate_symbols:
            return ordered[:top_k]

        selected: list[ScoredArticle] = []
        topic_keys: set[str] = set()
        per_symbol_count: dict[str, int] = {}

        for item in ordered:
            matched_symbols = item.breakdown.get("matched_symbols", [])
            if not matched_symbols:
                continue
            topic_key = cls._article_topic_key(item.article, matched_symbols)
            if topic_key in topic_keys:
                continue
            primary_symbol = matched_symbols[0]
            if per_symbol_count.get(primary_symbol, 0) >= 3:
                continue
            selected.append(item)
            topic_keys.add(topic_key)
            per_symbol_count[primary_symbol] = per_symbol_count.get(primary_symbol, 0) + 1
            if len(selected) >= top_k:
                break

        return selected

