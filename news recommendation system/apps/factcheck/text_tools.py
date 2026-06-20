import re

from apps.llm.models import LLMClaim
from apps.news.models import NewsEntity
from apps.portfolios.aliases import build_asset_aliases, build_contextual_asset_aliases, normalize_asset_text


class FactCheckTextMixin:
    @staticmethod
    def _tokenize(text: str) -> set[str]:
        tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9$:+.%/-]{2,}", text)
        return {token.lower() for token in tokens}

    @classmethod
    def _content_tokens(cls, text: str) -> set[str]:
        return {token for token in cls._tokenize(text) if len(token) >= 4 and not token.isdigit()}

    @classmethod
    def _latin_anchors(cls, text: str) -> set[str]:
        return {token.lower() for token in re.findall(r"\b[A-Z][A-Za-z0-9]{1,}\b", text or "")}

    @classmethod
    def _normalize_anchor(cls, value: str) -> str:
        normalized = re.sub(r"[^a-zа-яё0-9]+", " ", (value or "").lower().replace("ё", "е"))
        return re.sub(r"\s+", " ", normalized).strip()

    @classmethod
    def _anchor_tokens(cls, value: str) -> set[str]:
        return {token for token in cls._normalize_anchor(value).split() if len(token) >= 2}

    @classmethod
    def _quoted_anchors(cls, text: str) -> set[str]:
        anchors: set[str] = set()
        for value in re.findall(r"[«\"]([^»\"]{3,})[»\"]", text or ""):
            normalized = cls._normalize_anchor(value)
            tokens = cls._anchor_tokens(value)
            if normalized and tokens:
                anchors.add(normalized)
                anchors.update(tokens)
        return anchors

    @classmethod
    def _cyrillic_phrase_anchors(cls, text: str) -> set[str]:
        anchors: set[str] = set()
        phrase_pattern = re.compile(r"\b[А-ЯЁ][а-яё]{2,}(?:\s+[А-ЯЁ][а-яё]{2,})+\b")
        for match in phrase_pattern.finditer(text or ""):
            phrase = cls._normalize_anchor(match.group(0))
            tokens = cls._anchor_tokens(match.group(0))
            if len(tokens) < 2:
                continue
            anchors.add(phrase)
            anchors.update(tokens)
        return anchors

    @classmethod
    def _named_anchors(cls, text: str) -> set[str]:
        return cls._latin_anchors(text).union(cls._quoted_anchors(text)).union(cls._cyrillic_phrase_anchors(text))

    @classmethod
    def _entity_anchors(cls, entity: NewsEntity) -> set[str]:
        anchors: set[str] = set()
        values = [entity.ticker, entity.normalized, entity.text]
        for value in values:
            normalized = cls._normalize_anchor(value)
            if not normalized:
                continue
            tokens = cls._anchor_tokens(normalized)
            if not tokens:
                continue
            anchors.add(normalized)
            anchors.update(tokens)
        return anchors

    @classmethod
    def _matched_symbol_anchors(cls, claim: LLMClaim) -> set[str]:
        response = getattr(claim, "response", None)
        payload = getattr(response, "input_payload", {}) or {}
        symbols = payload.get("matched_symbols") or []
        anchors: set[str] = set()
        portfolio = getattr(response, "portfolio", None)
        normalized_symbols = {str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}
        if portfolio is not None and normalized_symbols:
            positions = portfolio.positions.select_related("asset").filter(asset__symbol__in=normalized_symbols)
            for position in positions:
                asset = position.asset
                anchors.update(build_asset_aliases(asset.symbol, asset.name, asset.exchange, asset.aliases))
                anchors.update(build_contextual_asset_aliases(asset.symbol, asset.name, asset.aliases))
        anchors.update(symbol.lower() for symbol in normalized_symbols)
        return {anchor for anchor in {cls._normalize_anchor(anchor) for anchor in anchors} if anchor}

    @classmethod
    def _claim_entity_anchors(cls, claim: LLMClaim, include_people: bool = True) -> set[str]:
        response = getattr(claim, "response", None)
        article = getattr(response, "article", None)
        if article is None:
            return set()

        anchors: set[str] = set()
        claim_tokens = cls._anchor_tokens(claim.claim_text).union(cls._latin_anchors(claim.claim_text))
        matched_symbol_anchors = cls._matched_symbol_anchors(claim)
        entity_types = {
            NewsEntity.EntityType.COMPANY,
            NewsEntity.EntityType.TICKER,
            NewsEntity.EntityType.ISIN,
        }
        if include_people:
            entity_types.add(NewsEntity.EntityType.PERSON)
        for entity in article.entities.all():
            if entity.entity_type in entity_types:
                entity_anchors = cls._entity_anchors(entity)
                entity_tokens = {
                    token
                    for anchor in entity_anchors
                    for token in cls._anchor_tokens(anchor).union({anchor})
                }
                if entity_tokens.intersection(claim_tokens) or entity_tokens.intersection(matched_symbol_anchors):
                    anchors.update(entity_anchors)
        return anchors

    @classmethod
    def _claim_anchors(cls, claim: LLMClaim) -> set[str]:
        return cls._named_anchors(claim.claim_text).union(cls._matched_symbol_anchors(claim)).union(cls._claim_entity_anchors(claim))

    @classmethod
    def _primary_claim_anchors(cls, claim: LLMClaim) -> set[str]:
        matched_symbol_anchors = cls._matched_symbol_anchors(claim)
        if matched_symbol_anchors:
            return matched_symbol_anchors
        return cls._claim_entity_anchors(claim, include_people=False)

    @classmethod
    def _anchors_support_claim(
        cls,
        claim_text: str,
        evidence_text: str,
        claim_anchors: set[str] | None = None,
        required_anchors: set[str] | None = None,
    ) -> bool:
        normalized_evidence = f" {normalize_asset_text(evidence_text)} "
        if required_anchors:
            return any(f" {normalize_asset_text(anchor)} " in normalized_evidence for anchor in required_anchors if anchor)

        evidence_anchors = cls._named_anchors(evidence_text)
        claim_latin = cls._latin_anchors(claim_text)
        evidence_latin = cls._latin_anchors(evidence_text)
        if claim_latin and claim_latin.intersection(evidence_latin):
            return True

        claim_anchors = claim_anchors if claim_anchors is not None else cls._named_anchors(claim_text)
        if not claim_anchors:
            return True
        return bool(claim_anchors.intersection(evidence_anchors))

    @classmethod
    def _extract_values(cls, text: str) -> dict[str, set[str]]:
        numeric_dates = set(re.findall(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b", text))
        textual_dates = set(
            re.findall(r"\b\d{1,2}\s+[A-Za-zА-Яа-яЁё]+\s+\d{4}\b", text, flags=re.IGNORECASE)
        )
        return {
            "dates": numeric_dates.union(textual_dates),
            "times": set(re.findall(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", text)),
            "percents": set(re.findall(r"(?<!\d)[+-]?\d+(?:[.,]\d+)?%", text)),
            "numbers": set(re.findall(r"\b\d+(?:[.,]\d+)?\b", text)),
            "tickers": {token.upper() for token in re.findall(r"\$?\b[A-Z]{2,5}\b", text)},
        }

    @classmethod
    def _normalize_structured_value(cls, value: str) -> str:
        cleaned = value.replace(",", ".").strip().upper().lstrip("+")
        numeric_match = re.match(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})$", cleaned)
        if numeric_match:
            day, month, year = numeric_match.groups()
            if len(year) == 2:
                year = f"20{year}"
            return f"{int(day):02d}.{int(month):02d}.{year}"
        return cleaned

