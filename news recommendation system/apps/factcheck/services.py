from apps.core.services import EmbeddingService, VectorStoreService
from apps.factcheck.models import Evidence, FactCheckResult
from apps.factcheck.retrieval import FactCheckRetrievalMixin
from apps.factcheck.scoring import FactCheckScoringMixin
from apps.factcheck.text_tools import FactCheckTextMixin
from apps.llm.models import LLMClaim
from apps.news.models import NewsChunk


class FactCheckService(FactCheckTextMixin, FactCheckRetrievalMixin, FactCheckScoringMixin):
    def __init__(self) -> None:
        self.embedding = EmbeddingService()
        self.vector_store = VectorStoreService()
        self._semantic_cache: dict[str, list[float]] = {}

    def check_claim(self, claim: LLMClaim) -> FactCheckResult:
        source_candidates = self._retrieve_source_candidates(claim)
        candidates = self._retrieve_candidates(claim)
        source_scored: list[tuple[NewsChunk | None, str, float, str | None]] = []
        source_label, source_score, source_excerpt = self._score_source_article(claim)
        if source_score > 0:
            source_scored.append((None, "source_support", max(source_score, 0.62), source_excerpt))
        for chunk in source_candidates:
            label, score = self._score_candidate(claim, chunk)
            if score > 0:
                source_scored.append((chunk, "source_support", max(score, 0.62), None))
        scored: list[tuple[NewsChunk, str, float]] = []
        for chunk in candidates:
            label, score = self._score_candidate(claim, chunk)
            if score > 0:
                scored.append((chunk, label, score))
        scored.sort(key=lambda item: item[2], reverse=True)
        source_scored.sort(key=lambda item: item[2], reverse=True)

        support_hits = [item for item in scored if item[1] == "support"]
        contradict_hits = [item for item in scored if item[1] == "contradict"]
        related_hits = [item for item in scored if item[1] == "related"]
        independent_contradict_hits = [item for item in contradict_hits if self._is_independent_chunk(claim, item[0])]

        best_source_support = source_scored[0][2] if source_scored else 0.0
        best_support = support_hits[0][2] if support_hits else 0.0
        best_contradict = independent_contradict_hits[0][2] if independent_contradict_hits else 0.0
        support_articles = len({chunk.article_id for chunk, _, _ in support_hits[:3]})
        contradict_articles = len({chunk.article_id for chunk, _, _ in independent_contradict_hits[:3]})

        if best_contradict >= 0.58 and best_contradict >= max(best_support, best_source_support) + 0.05:
            status = LLMClaim.VerificationStatus.CONTRADICTED
            confidence = min(1.0, best_contradict + 0.05 * max(contradict_articles - 1, 0))
            explanation = "Другие статьи из корпуса содержат независимые фрагменты, противоречащие утверждению."
            top = [(chunk, label, score, None) for chunk, label, score in independent_contradict_hits[:3]] + source_scored[:2]
        elif best_source_support >= 0.62:
            status = LLMClaim.VerificationStatus.CONFIRMED
            confidence = min(1.0, best_source_support + 0.08 * max(support_articles, 0))
            if support_hits:
                explanation = "Утверждение подтверждено исходной публикацией и найдено дополнительное подтверждение в корпусе."
            else:
                explanation = "Утверждение подтверждено исходной публикацией; независимого дубля в корпусе пока нет."
            top = source_scored[:2] + [(chunk, label, score, None) for chunk, label, score in support_hits[:3]]
        elif best_support >= 0.5:
            status = LLMClaim.VerificationStatus.CONFIRMED
            confidence = min(1.0, best_support + 0.05 * max(support_articles - 1, 0))
            explanation = "Утверждение подтверждено другими сообщениями корпуса."
            top = [(chunk, label, score, None) for chunk, label, score in support_hits[:4]] + source_scored[:1]
        elif scored or related_hits or source_scored:
            status = LLMClaim.VerificationStatus.NOT_CONFIRMED
            confidence = max(
                best_source_support,
                best_support,
                best_contradict,
                related_hits[0][2] if related_hits else 0.0,
                scored[0][2] if scored else 0.0,
            )
            explanation = "Найдены похожие фрагменты, но они не дают достаточно сильного подтверждения или независимого опровержения."
            top = [
                item
                for item in (
                    source_scored
                    + [(chunk, label, score, None) for chunk, label, score in support_hits + independent_contradict_hits]
                )[:5]
            ]
        else:
            status = LLMClaim.VerificationStatus.INSUFFICIENT
            confidence = max(
                best_source_support,
                best_support,
                best_contradict,
                related_hits[0][2] if related_hits else 0.0,
                support_hits[0][2] * 0.7 if support_hits else 0.0,
            )
            explanation = "Исходная публикация и корпус не дают достаточно сильного подтверждения или опровержения."
            top = [
                item
                for item in (
                    source_scored
                    + [(chunk, label, score, None) for chunk, label, score in support_hits + independent_contradict_hits]
                )[:5]
            ]

        result, _ = FactCheckResult.objects.update_or_create(
            claim=claim,
            defaults={
                "status": status,
                "confidence": confidence,
                "explanation": explanation,
                "evidence_count": len(top),
            },
        )
        result.evidences.all().delete()
        Evidence.objects.bulk_create(
            [
                Evidence(
                    result=result,
                    article=chunk.article if chunk is not None else claim.response.article,
                    chunk=chunk,
                    excerpt=excerpt if excerpt is not None else chunk.text[:500],
                    url=chunk.article.url if chunk is not None else claim.response.article.url,
                    score=score,
                    label=label,
                )
                for chunk, label, score, excerpt in top
            ]
        )
        claim.status = status
        claim.save(update_fields=["status", "updated_at"])
        return result

    def check_response_claims(self, response_id: int) -> list[FactCheckResult]:
        claims = list(LLMClaim.objects.filter(response_id=response_id).select_related("response", "response__article", "response__article__source"))
        if not claims:
            return []

        existing_results = {
            result.claim_id: result
            for result in FactCheckResult.objects.filter(claim__in=claims).prefetch_related("evidences")
        }
        results: list[FactCheckResult] = []
        for claim in claims:
            cached_result = existing_results.get(claim.id)
            if cached_result and self._can_reuse_result(claim, cached_result):
                results.append(cached_result)
                continue
            results.append(self.check_claim(claim))
        return results
