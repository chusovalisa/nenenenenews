import re

from apps.llm.models import LLMClaim
from apps.news.models import NewsArticle, NewsChunk


class FactCheckScoringMixin:
    def _semantic_vector(self, text: str) -> list[float]:
        normalized = re.sub(r"\s+", " ", text or "").strip()
        if not normalized:
            return []
        cache_key = normalized[:3000]
        if cache_key not in self._semantic_cache:
            vectors = self.embedding.embed([cache_key])
            self._semantic_cache[cache_key] = vectors[0] if vectors else []
        return self._semantic_cache[cache_key]

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

    def _semantic_similarity(self, claim_text: str, evidence_text: str) -> float:
        return self._cosine_similarity(
            self._semantic_vector(claim_text),
            self._semantic_vector(evidence_text),
        )

    def _score_text(self, claim: LLMClaim, text: str, is_trusted: bool = False) -> tuple[str, float]:
        claim_values = self._extract_values(claim.claim_text)
        chunk_values = self._extract_values(text)
        normalized_claim_values = {
            key: {self._normalize_structured_value(value) for value in values}
            for key, values in claim_values.items()
        }
        normalized_chunk_values = {
            key: {self._normalize_structured_value(value) for value in values}
            for key, values in chunk_values.items()
        }
        shared_values = 0
        conflicting_values = 0
        exact_matches_by_bucket: dict[str, bool] = {}
        comparison_keys = ["dates", "times", "percents"]
        if not any(normalized_claim_values[key] for key in comparison_keys):
            comparison_keys.append("numbers")
        for key in comparison_keys:
            claim_bucket = normalized_claim_values[key]
            chunk_bucket = normalized_chunk_values[key]
            if claim_bucket and chunk_bucket:
                if claim_bucket.intersection(chunk_bucket):
                    shared_values += 1
                    exact_matches_by_bucket[key] = True
                else:
                    conflicting_values += 1
                    exact_matches_by_bucket[key] = False
        shared_tickers = len(normalized_claim_values["tickers"].intersection(normalized_chunk_values["tickers"]))
        claim_tokens = self._content_tokens(claim.claim_text)
        evidence_tokens = self._content_tokens(text)
        shared_content_tokens = claim_tokens.intersection(evidence_tokens)
        claim_anchors = self._claim_anchors(claim)
        primary_claim_anchors = self._primary_claim_anchors(claim)
        anchor_tokens = {token for anchor in claim_anchors for token in self._anchor_tokens(anchor)}
        specific_claim_tokens = claim_tokens.difference(anchor_tokens)
        shared_specific_tokens = shared_content_tokens.difference(anchor_tokens)
        content_overlap = len(shared_specific_tokens) / max(len(specific_claim_tokens), 1)
        anchors_match = self._anchors_support_claim(
            claim.claim_text,
            text,
            claim_anchors=claim_anchors,
            required_anchors=primary_claim_anchors,
        )
        claim_has_structured_values = any(normalized_claim_values[key] for key in comparison_keys)
        chunk_has_structured_values = any(normalized_chunk_values[key] for key in comparison_keys)
        has_exact_structured_match = shared_values > 0
        claim_requires_date_match = bool(normalized_claim_values["dates"])
        claim_requires_time_match = bool(normalized_claim_values["times"])
        claim_requires_percent_match = bool(normalized_claim_values["percents"])
        semantic = self._semantic_similarity(claim.claim_text, text)
        trusted_bonus = 0.08 if is_trusted else 0.0

        support_score = semantic + shared_values * 0.12 + min(shared_tickers, 2) * 0.08 + trusted_bonus
        contradict_score = semantic * 0.8 + conflicting_values * 0.18 + trusted_bonus

        if claim_anchors and not anchors_match:
            return "irrelevant", 0.0

        ticker_required = bool(normalized_claim_values["tickers"])
        ticker_mismatch = ticker_required and shared_tickers == 0 and not anchors_match
        if ticker_mismatch:
            if conflicting_values and semantic >= 0.45:
                return "related", round(float(min(1.0, contradict_score * 0.65)), 6)
            return "irrelevant", 0.0

        if claim_requires_date_match and chunk_has_structured_values and not exact_matches_by_bucket.get("dates", False):
            if semantic >= 0.45:
                return "related", round(float(min(1.0, max(support_score, contradict_score) * 0.45)), 6)
            return "irrelevant", 0.0

        if claim_requires_time_match and chunk_has_structured_values and not exact_matches_by_bucket.get("times", False):
            if semantic >= 0.45:
                return "related", round(float(min(1.0, max(support_score, contradict_score) * 0.45)), 6)
            return "irrelevant", 0.0

        if claim_requires_percent_match and chunk_has_structured_values and not exact_matches_by_bucket.get("percents", False):
            if semantic >= 0.45:
                return "related", round(float(min(1.0, max(support_score, contradict_score) * 0.45)), 6)
            return "irrelevant", 0.0

        if claim_has_structured_values and chunk_has_structured_values and not has_exact_structured_match:
            if semantic >= 0.45:
                if conflicting_values:
                    return "contradict", round(float(min(1.0, contradict_score * 0.85)), 6)
                return "related", round(float(min(1.0, support_score * 0.55)), 6)
            return "irrelevant", 0.0

        has_specific_support = bool(
            shared_values
            or len(shared_specific_tokens) >= 3
            or (shared_tickers and len(shared_specific_tokens) >= 2)
        )

        if conflicting_values and semantic >= 0.5 and contradict_score >= support_score + 0.06:
            return "contradict", round(float(min(1.0, contradict_score)), 6)
        if (
            anchors_match
            and has_specific_support
            and support_score >= 0.52
            and (content_overlap >= 0.12 or shared_values or shared_tickers)
        ):
            return "support", round(float(min(1.0, support_score)), 6)
        if semantic >= 0.38 and (shared_content_tokens or shared_values or shared_tickers):
            return "related", round(float(min(1.0, max(support_score, contradict_score) * 0.8)), 6)
        return "irrelevant", 0.0

    def _score_candidate(self, claim: LLMClaim, chunk: NewsChunk) -> tuple[str, float]:
        return self._score_text(claim, chunk.text, is_trusted=chunk.article.source.is_trusted)

    def _score_source_article(self, claim: LLMClaim) -> tuple[str, float, str]:
        article: NewsArticle = claim.response.article
        source_text = " ".join([article.title or "", article.summary or "", article.content or ""]).strip()
        label, score = self._score_text(claim, source_text, is_trusted=article.source.is_trusted)
        if score <= 0:
            shared_tokens = self._content_tokens(claim.claim_text).intersection(self._content_tokens(source_text))
            overlap = len(shared_tokens) / max(len(self._content_tokens(claim.claim_text)), 1)
            claim_values = self._extract_values(claim.claim_text)
            source_values = self._extract_values(source_text)
            comparable_buckets = ("dates", "times", "percents")
            has_structured_conflict = any(
                claim_values[bucket]
                and source_values[bucket]
                and not {
                    self._normalize_structured_value(value)
                    for value in claim_values[bucket]
                }.intersection({self._normalize_structured_value(value) for value in source_values[bucket]})
                for bucket in comparable_buckets
            )
            if (
                self._anchors_support_claim(
                    claim.claim_text,
                    source_text,
                    claim_anchors=self._claim_anchors(claim),
                    required_anchors=self._primary_claim_anchors(claim),
                )
                and not has_structured_conflict
                and (len(shared_tokens) >= 2 or self._primary_claim_anchors(claim))
            ):
                label = "support"
                score = 0.62
        excerpt = source_text[:500]
        return label, score, excerpt

