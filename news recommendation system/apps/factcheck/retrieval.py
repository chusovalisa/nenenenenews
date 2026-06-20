from django.db.models import Q

from apps.factcheck.models import FactCheckResult
from apps.llm.models import LLMClaim
from apps.news.models import NewsChunk


class FactCheckRetrievalMixin:
    def _strict_candidate_query(self, claim: LLMClaim) -> Q | None:
        values = self._extract_values(claim.claim_text)
        query = Q()
        has_constraints = False

        if values["tickers"]:
            ticker_query = Q()
            for ticker in values["tickers"]:
                ticker_query |= Q(text__icontains=ticker) | Q(article__title__icontains=ticker)
            query &= ticker_query
            has_constraints = True

        for bucket in ("dates", "times", "percents"):
            if values[bucket]:
                bucket_query = Q()
                for value in values[bucket]:
                    bucket_query |= Q(text__icontains=value) | Q(article__title__icontains=value)
                query &= bucket_query
                has_constraints = True

        return query if has_constraints else None

    @staticmethod
    def _distinct_articles(chunks: list[NewsChunk]) -> list[NewsChunk]:
        seen: set[tuple[int, int]] = set()
        ordered: list[NewsChunk] = []
        for chunk in chunks:
            key = (chunk.article_id, chunk.chunk_index)
            if key in seen:
                continue
            seen.add(key)
            ordered.append(chunk)
        return ordered

    @staticmethod
    def _prioritize_chunks(chunks: list[NewsChunk], source_article_id: int) -> list[NewsChunk]:
        def sort_key(chunk: NewsChunk):
            return (
                0 if chunk.article.source.is_trusted else 1,
                0 if chunk.article_id != source_article_id else 1,
                -chunk.article.published_at.timestamp(),
                chunk.chunk_index,
            )

        return sorted(chunks, key=sort_key)

    def _retrieve_candidates(self, claim: LLMClaim, top_k: int = 8) -> list[NewsChunk]:
        source_article_id = claim.response.article_id
        candidates = self._retrieve_candidates_db(claim, source_article_id=source_article_id, top_k=top_k * 4)
        if len(candidates) < top_k * 2 and not self.embedding.is_fallback:
            qdrant_candidates = self._retrieve_candidates_qdrant(claim, source_article_id=source_article_id, top_k=top_k * 4)
            candidates.extend(qdrant_candidates)
        prioritized = self._prioritize_chunks(self._distinct_articles(candidates), source_article_id=source_article_id)
        return prioritized[: top_k * 4]

    def _retrieve_source_candidates(self, claim: LLMClaim, top_k: int = 3) -> list[NewsChunk]:
        source_article_id = claim.response.article_id
        chunks = (
            NewsChunk.objects.filter(article_id=source_article_id)
            .select_related("article", "article__source")
            .order_by("chunk_index")
        )
        scored = []
        for chunk in chunks:
            _, score = self._score_candidate(claim, chunk)
            if score > 0:
                scored.append((chunk, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return [chunk for chunk, _ in scored[:top_k]]

    @staticmethod
    def _publisher_key(chunk: NewsChunk) -> str:
        config = chunk.article.source.config or {}
        return str(config.get("publisher") or chunk.article.source.slug)

    def _is_independent_chunk(self, claim: LLMClaim, chunk: NewsChunk) -> bool:
        source_config = claim.response.article.source.config or {}
        source_publisher = str(source_config.get("publisher") or claim.response.article.source.slug)
        return self._publisher_key(chunk) != source_publisher

    def _can_reuse_result(self, claim: LLMClaim, result: FactCheckResult) -> bool:
        evidences = list(result.evidences.all())
        if result.status == LLMClaim.VerificationStatus.INSUFFICIENT and not any(
            evidence.label == "source_support" for evidence in evidences
        ):
            return False
        if result.status == LLMClaim.VerificationStatus.NOT_CONFIRMED and any(
            evidence.label in {"support", "source_support"} for evidence in evidences
        ):
            return False
        if result.status == LLMClaim.VerificationStatus.CONFIRMED and not evidences:
            return False
        if result.status == LLMClaim.VerificationStatus.CONFIRMED and any(
            evidence.label == "related" for evidence in evidences
        ):
            return False
        return True

    def _retrieve_candidates_qdrant(self, claim: LLMClaim, source_article_id: int, top_k: int = 5) -> list[NewsChunk]:
        vectors = self.embedding.embed([claim.claim_text])
        if not vectors:
            return []
        hits = self.vector_store.search(vectors[0], limit=top_k * 3)
        if not hits:
            return []
        payloads = [hit.get("payload") or {} for hit in hits]
        article_ids = [payload.get("article_id") for payload in payloads if payload.get("article_id") != source_article_id]
        chunk_indexes = [payload.get("chunk_index") for payload in payloads if payload.get("article_id") != source_article_id]
        if not article_ids or not chunk_indexes:
            return []
        key_order = [
            (payload.get("article_id"), payload.get("chunk_index"))
            for payload in payloads
            if payload.get("article_id") != source_article_id
        ]
        chunks = (
            NewsChunk.objects.filter(article_id__in=article_ids, chunk_index__in=chunk_indexes)
            .exclude(article_id=source_article_id)
            .select_related("article", "article__source")
        )
        chunk_map = {(chunk.article_id, chunk.chunk_index): chunk for chunk in chunks}
        ordered = [chunk_map[key] for key in key_order if key in chunk_map]
        return ordered[: top_k * 3]

    def _retrieve_candidates_db(self, claim: LLMClaim, source_article_id: int, top_k: int = 5) -> list[NewsChunk]:
        strict_query = self._strict_candidate_query(claim)
        base_qs = (
            NewsChunk.objects.exclude(article_id=source_article_id)
            .select_related("article", "article__source")
        )
        if strict_query is not None:
            strict_matches = list(
                base_qs.filter(strict_query).order_by("-article__source__is_trusted", "-article__published_at")[: top_k * 3]
            )
            if strict_matches:
                return strict_matches
        tokens = self._content_tokens(claim.claim_text)
        query = Q()
        for token in list(tokens)[:10]:
            query |= Q(text__icontains=token) | Q(article__title__icontains=token)
        if not query:
            return []
        return list(
            base_qs.filter(query)
            .order_by("-article__source__is_trusted", "-article__published_at")[: top_k * 3]
        )

