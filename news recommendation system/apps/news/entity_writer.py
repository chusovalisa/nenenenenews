from apps.news.models import NewsArticle, NewsEntity


class EntityWriterMixin:
    @staticmethod
    def _append_entity(
        entities: list[NewsEntity],
        seen: set[tuple[str, str]],
        *,
        article: NewsArticle,
        entity_type: str,
        text: str,
        normalized: str = "",
        ticker: str = "",
        confidence: float = 0.5,
    ) -> None:
        key = (entity_type, normalized or text)
        if key in seen:
            return
        seen.add(key)
        entities.append(
            NewsEntity(
                article=article,
                entity_type=entity_type,
                text=text[:255],
                normalized=(normalized or text)[:255],
                ticker=ticker[:32],
                confidence=confidence,
            )
        )

