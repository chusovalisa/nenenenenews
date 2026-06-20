import logging
import re

from natasha import DatesExtractor, Doc, MorphVocab, NewsEmbedding, NewsNERTagger, Segmenter

from apps.news.entity_aliases import EntityAliasMixin
from apps.news.entity_utils import NOISE_TICKERS, extract_isins
from apps.news.entity_writer import EntityWriterMixin
from apps.news.models import NewsArticle, NewsEntity

logger = logging.getLogger(__name__)


class EntityExtractor(EntityAliasMixin, EntityWriterMixin):
    TICKER_RE = re.compile(r"\$?\b[A-Z]{1,5}\b")
    MAX_LEARNED_ALIAS_LENGTH = 120

    def __init__(self) -> None:
        self.segmenter = Segmenter()
        self.morph_vocab = MorphVocab()
        self.dates_extractor = DatesExtractor(self.morph_vocab)
        try:
            self.embedding = NewsEmbedding()
            self.ner_tagger = NewsNERTagger(self.embedding)
        except Exception as exc:
            logger.warning("Natasha NER is unavailable, org extraction fallback used: %s", exc)
            self.embedding = None
            self.ner_tagger = None
        self.assets_by_symbol = self._load_assets()
        self.asset_aliases = self._build_asset_aliases()

    def extract(self, article: NewsArticle) -> list[NewsEntity]:
        seen: set[tuple[str, str]] = set()
        entities: list[NewsEntity] = []
        text = f"{article.title} {article.summary} {article.content}"
        article_known_symbols = self._article_known_symbols(article, text)

        for isin in extract_isins(text):
            self._append_entity(
                entities,
                seen,
                article=article,
                entity_type=NewsEntity.EntityType.ISIN,
                text=isin,
                normalized=isin,
                confidence=0.95,
            )

        for match in self.TICKER_RE.findall(text):
            symbol = match.replace("$", "")
            if len(symbol) < 2:
                continue
            if symbol in NOISE_TICKERS:
                continue
            self._append_entity(
                entities,
                seen,
                article=article,
                entity_type=NewsEntity.EntityType.TICKER,
                text=match,
                normalized=symbol,
                ticker=symbol,
                confidence=0.7,
            )

        if self.ner_tagger is not None:
            try:
                doc = Doc(text[:12000])
                doc.segment(self.segmenter)
                doc.tag_ner(self.ner_tagger)
                for span in doc.spans:
                    if span.type != "ORG":
                        continue
                    company_text = text[span.start:span.stop].strip()
                    normalized_company = self._normalize_text(company_text)
                    if len(normalized_company) < 3:
                        continue
                    self._append_entity(
                        entities,
                        seen,
                        article=article,
                        entity_type=NewsEntity.EntityType.COMPANY,
                        text=company_text,
                        normalized=normalized_company,
                        confidence=0.82,
                    )
                    matched_symbols = self._match_asset_symbols(normalized_company, self.asset_aliases)
                    for symbol in matched_symbols:
                        for asset in self.assets_by_symbol.get(symbol, []):
                            if self._can_learn_alias(article, asset, company_text, text):
                                self._learn_alias_for_symbol(symbol, company_text)
                                break
                    for symbol in sorted(article_known_symbols):
                        if symbol in matched_symbols:
                            continue
                        for asset in self.assets_by_symbol.get(symbol, []):
                            if self._can_learn_alias(article, asset, company_text, text):
                                self._learn_alias_for_symbol(symbol, company_text)
                                matched_symbols.append(symbol)
                                break
                    for symbol in matched_symbols:
                        self._append_entity(
                            entities,
                            seen,
                            article=article,
                            entity_type=NewsEntity.EntityType.TICKER,
                            text=symbol,
                            normalized=symbol,
                            ticker=symbol,
                            confidence=0.88,
                        )
            except Exception as exc:
                logger.warning("Natasha ORG extraction failed for article %s: %s", article.id, exc)

        try:
            for match in self.dates_extractor(text[:8000]):
                date_text = text[match.start:match.stop].strip()
                fact = match.fact
                parts = []
                if getattr(fact, "day", None):
                    parts.append(f"{int(fact.day):02d}")
                if getattr(fact, "month", None):
                    parts.append(f"{int(fact.month):02d}")
                if getattr(fact, "year", None):
                    parts.append(str(int(fact.year)))
                normalized_date = ".".join(parts) if len(parts) == 3 else date_text
                self._append_entity(
                    entities,
                    seen,
                    article=article,
                    entity_type=NewsEntity.EntityType.DATE,
                    text=date_text,
                    normalized=normalized_date,
                    confidence=0.78,
                )
        except Exception as exc:
            logger.warning("Natasha DATE extraction failed for article %s: %s", article.id, exc)
        return entities
