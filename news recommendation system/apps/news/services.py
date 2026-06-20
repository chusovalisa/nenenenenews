import hashlib
import json
import logging
import re
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.core.services import EmbeddingService, RuntimeConfigService, VectorStoreService
from apps.news.adapters import API_ADAPTERS, UnifiedNewsItem
from apps.news.entity_extractor import EntityExtractor
from apps.news.entity_utils import extract_isins
from apps.news.models import NewsArticle, NewsChunk, NewsEntity, NewsSource
from apps.portfolios.models import Asset

logger = logging.getLogger(__name__)

def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _iter_children_by_name(element: ElementTree.Element, *names: str):
    wanted = {name.lower() for name in names}
    for child in list(element):
        if _local_name(child.tag).lower() in wanted:
            yield child


def _first_text(element: ElementTree.Element, *names: str) -> str:
    for child in _iter_children_by_name(element, *names):
        text = "".join(child.itertext()).strip()
        if text:
            return text
    return ""


def _first_attr(element: ElementTree.Element, attr: str, *names: str) -> str:
    for child in _iter_children_by_name(element, *names):
        value = (child.attrib.get(attr) or "").strip()
        if value:
            return value
    return ""


def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_datetime(raw: str | None) -> datetime:
    if not raw:
        return timezone.now()
    value = raw.strip()
    if not value:
        return timezone.now()
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed.astimezone(timezone.get_current_timezone())
    except (TypeError, ValueError, IndexError):
        parsed_dt = parse_datetime(value)
        if parsed_dt:
            if timezone.is_naive(parsed_dt):
                parsed_dt = timezone.make_aware(parsed_dt, timezone.get_current_timezone())
            return parsed_dt.astimezone(timezone.get_current_timezone())
    return timezone.now()


@dataclass
class RawNewsItem:
    external_id: str
    url: str
    title: str
    summary: str
    content: str
    published_at: datetime
    language: str
    metadata: dict[str, Any]


class RSSNewsConnector:
    @staticmethod
    def _build_ssl_context(source: NewsSource) -> ssl.SSLContext:
        verify_ssl = source.config.get("verify_ssl", True)
        if not verify_ssl:
            return ssl._create_unverified_context()
        try:
            import certifi

            return ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            return ssl.create_default_context()

    def _extract_url(self, item: ElementTree.Element) -> str:
        link = _first_text(item, "link")
        if link:
            return link
        for child in _iter_children_by_name(item, "link"):
            href = (child.attrib.get("href") or "").strip()
            rel = (child.attrib.get("rel") or "alternate").strip()
            if href and rel in {"", "alternate"}:
                return href
        return ""

    def _extract_content(self, item: ElementTree.Element) -> tuple[str, str]:
        summary = _strip_html(_first_text(item, "description", "summary", "subtitle"))
        content = _strip_html(_first_text(item, "encoded", "content", "full-text"))
        if not content:
            content = summary
        return summary, content

    @staticmethod
    def _parse_spbexchange_html(html: str, source: NewsSource) -> list[RawNewsItem]:
        pattern = re.compile(
            r'\{"id":(?P<id>\d+),"url":"(?P<url>[^"]+)","title":"(?P<title>(?:\\.|[^"])*)".*?"startPublish":"(?P<date>[^"]+)".*?"sectionName":"(?P<section>(?:\\.|[^"])*)"',
            re.DOTALL,
        )
        output: list[RawNewsItem] = []
        seen_urls: set[str] = set()
        for match in pattern.finditer(html):
            item_url = unescape(json.loads(f'"{match.group("url")}"'))
            title = _strip_html(unescape(json.loads(f'"{match.group("title")}"')))
            section_name = _strip_html(unescape(json.loads(f'"{match.group("section")}"')))
            if not item_url or not title:
                continue
            article_url = f"https://spbexchange.ru/ru/about/news/{item_url}"
            if article_url in seen_urls:
                continue
            seen_urls.add(article_url)
            output.append(
                RawNewsItem(
                    external_id=match.group("id"),
                    url=article_url,
                    title=title,
                    summary=section_name,
                    content=f"{title}. {section_name}".strip(". "),
                    published_at=_parse_datetime(match.group("date")),
                    language=source.config.get("language", "ru"),
                    metadata={"feed_url": source.base_url, "parser": "spbexchange_news"},
                )
            )
        return output

    @staticmethod
    def _parse_namex_html(html: str, source: NewsSource) -> list[RawNewsItem]:
        pattern = re.compile(
            r"<tr valign=top><td align=right nowrap>(?P<date>[^<]+)</td><td width='100%'><a class='newslink' href='(?P<href>[^']+)'>(?P<title>.*?)</a>",
            re.DOTALL,
        )
        output: list[RawNewsItem] = []
        seen_urls: set[str] = set()
        for match in pattern.finditer(html):
            href = unescape(match.group("href")).strip()
            title = _strip_html(unescape(match.group("title")))
            if not href or not title:
                continue
            article_url = href if href.startswith("http") else f"https://www.namex.org{href}"
            if article_url in seen_urls:
                continue
            seen_urls.add(article_url)
            output.append(
                RawNewsItem(
                    external_id=article_url.rsplit("/", 1)[-1],
                    url=article_url,
                    title=title,
                    summary="Новости НТБ",
                    content=title,
                    published_at=_parse_datetime(match.group("date").strip()),
                    language=source.config.get("language", "ru"),
                    metadata={"feed_url": source.base_url, "parser": "namex_news"},
                )
            )
        return output

    def _rss_items(self, root: ElementTree.Element) -> list[ElementTree.Element]:
        return [node for node in root.iter() if _local_name(node.tag).lower() == "item"]

    def _atom_entries(self, root: ElementTree.Element) -> list[ElementTree.Element]:
        return [node for node in root.iter() if _local_name(node.tag).lower() == "entry"]

    def fetch(self, source: NewsSource) -> list[RawNewsItem]:
        request = Request(source.base_url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=15, context=self._build_ssl_context(source)) as response:
            data = response.read()
        parser = str(source.config.get("parser") or "").strip()
        if parser == "spbexchange_news":
            return self._parse_spbexchange_html(data.decode("utf-8", errors="ignore"), source)
        if parser == "namex_news":
            return self._parse_namex_html(data.decode("utf-8", errors="ignore"), source)
        try:
            parsed_items = self._parse_feedparser(data, source)
            if parsed_items:
                return parsed_items
        except Exception as exc:
            logger.warning("feedparser failed for %s, XML fallback used: %s", source.slug, exc)
        root = ElementTree.fromstring(data)
        output: list[RawNewsItem] = []
        feed_lang = source.config.get("language") or root.attrib.get("{http://www.w3.org/XML/1998/namespace}lang") or "ru"
        entries = self._rss_items(root)
        if not entries:
            entries = self._atom_entries(root)
        for item in entries:
            link = self._extract_url(item)
            title = _strip_html(_first_text(item, "title"))
            summary, content = self._extract_content(item)
            guid = (_first_text(item, "guid", "id") or link or title).strip()
            published_at = _parse_datetime(
                _first_text(item, "pubDate", "published", "updated", "dc:date", "date")
            )
            if not title or not link:
                continue
            output.append(
                RawNewsItem(
                    external_id=guid,
                    url=link,
                    title=title,
                    summary=summary,
                    content=content or summary or title,
                    published_at=published_at,
                    language=feed_lang,
                    metadata={"feed_url": source.base_url},
                )
            )
        return output

    def _parse_feedparser(self, data: bytes, source: NewsSource) -> list[RawNewsItem]:
        import feedparser

        feed = feedparser.parse(data)
        if getattr(feed, "bozo", False) and not feed.entries:
            raise ValueError(getattr(feed, "bozo_exception", "invalid feed"))
        output: list[RawNewsItem] = []
        feed_lang = source.config.get("language") or getattr(feed.feed, "language", "") or "ru"
        for entry in feed.entries:
            title = _strip_html(getattr(entry, "title", "") or "")
            link = getattr(entry, "link", "") or ""
            summary = _strip_html(getattr(entry, "summary", "") or getattr(entry, "description", "") or "")
            content_blocks = getattr(entry, "content", []) or []
            content = ""
            if content_blocks:
                content = _strip_html(content_blocks[0].get("value", ""))
            content = content or summary or title
            published_raw = (
                getattr(entry, "published", "")
                or getattr(entry, "updated", "")
                or getattr(entry, "created", "")
            )
            if not title or not link:
                continue
            output.append(
                RawNewsItem(
                    external_id=(getattr(entry, "id", "") or link or title).strip(),
                    url=link,
                    title=title,
                    summary=summary,
                    content=content,
                    published_at=_parse_datetime(published_raw),
                    language=feed_lang,
                    metadata={"feed_url": source.base_url, "parser": "feedparser"},
                )
            )
        return output


class APINewsConnector:
    def __init__(self, lookback_days: int | None = None) -> None:
        self.http = RSSNewsConnector()
        self.lookback_days = lookback_days

    @staticmethod
    def _tracked_symbols() -> list[str]:
        seen: set[str] = set()
        symbols: list[str] = []
        for symbol in Asset.objects.exclude(symbol="").values_list("symbol", flat=True):
            normalized = (symbol or "").strip().upper()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            symbols.append(normalized)
        return symbols

    def _fetch_json(self, url: str, source: NewsSource) -> dict[str, Any]:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=15, context=self.http._build_ssl_context(source)) as response:
            return json.loads(response.read().decode("utf-8"))

    def _fetch_moex_dividends(self, source: NewsSource) -> list[RawNewsItem]:
        url_template = source.base_url
        output: list[RawNewsItem] = []
        min_year = int(source.config.get("min_year", timezone.now().year - 1))
        for symbol in self._tracked_symbols():
            try:
                payload = self._fetch_json(url_template.format(symbol=symbol), source)
            except Exception as exc:
                logger.warning("MOEX dividends fetch failed for %s via %s: %s", symbol, source.slug, exc)
                continue
            dividends = payload.get("dividends", {})
            columns = dividends.get("columns") or []
            rows = dividends.get("data") or []
            for row in rows[-3:]:
                item = dict(zip(columns, row))
                registry_date = str(item.get("registryclosedate") or "").strip()
                if not registry_date or not registry_date[:4].isdigit() or int(registry_date[:4]) < min_year:
                    continue
                value = item.get("value")
                currency = item.get("currencyid") or ""
                isin = item.get("isin") or ""
                title = f"Дивиденды по {symbol}: {value} {currency}".strip()
                content = (
                    f"Для бумаги {symbol} зафиксировано корпоративное событие по дивидендам. "
                    f"Дата закрытия реестра: {registry_date}. Значение дивиденда: {value} {currency}. "
                    f"ISIN: {isin}."
                )
                article_url = f"https://iss.moex.com/iss/securities/{symbol}/dividends.json#registryclosedate={registry_date}"
                output.append(
                    RawNewsItem(
                        external_id=f"{symbol}:{registry_date}",
                        url=article_url,
                        title=title,
                        summary=f"Дивидендная запись MOEX ISS для {symbol}",
                        content=content,
                        published_at=_parse_datetime(registry_date),
                        language=source.config.get("language", "ru"),
                        metadata={"feed_url": source.base_url, "symbol": symbol, "parser": "moex_dividends_api"},
                    )
                )
        return output

    def fetch(self, source: NewsSource) -> list[RawNewsItem]:
        parser = str(source.config.get("parser") or "").strip()
        if parser == "moex_dividends_api":
            return self._fetch_moex_dividends(source)
        adapter_cls = API_ADAPTERS.get(parser)
        if adapter_cls:
            return [self._to_raw_news(item, source) for item in adapter_cls(source, lookback_days=self.lookback_days).fetch()]
        return []

    @staticmethod
    def _to_raw_news(item: UnifiedNewsItem, source: NewsSource) -> RawNewsItem:
        metadata = dict(item.metadata or {})
        metadata.setdefault("feed_url", source.base_url)
        if item.tickers:
            metadata["tickers"] = item.tickers
        if item.isins:
            metadata["isins"] = item.isins
        return RawNewsItem(
            external_id=item.external_id,
            url=item.url,
            title=item.title,
            summary=item.summary,
            content=item.content,
            published_at=item.published_at,
            language=item.language,
            metadata=metadata,
        )

class NewsIngestionService:
    def __init__(self) -> None:
        self.embedding_service = EmbeddingService()
        self.vector_store = VectorStoreService()
        self.entity_extractor = EntityExtractor()

    @staticmethod
    def _normalize_lookback_days(value: int | str | None) -> int:
        default = RuntimeConfigService.get("NEWS_LOOKBACK_DAYS", 1)
        try:
            return max(1, min(int(value or default), 365))
        except (TypeError, ValueError):
            return max(1, int(default))

    @staticmethod
    def _hash_text(title: str, content: str) -> str:
        raw = f"{title.strip()}::{content.strip()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _split_chunks(text: str, chunk_size: int = 400) -> list[str]:
        words = text.split()
        chunks: list[str] = []
        for i in range(0, len(words), chunk_size):
            piece = " ".join(words[i : i + chunk_size]).strip()
            if piece:
                chunks.append(piece)
        return chunks or [text]

    def _resolve_sources(self) -> list[NewsSource]:
        db_sources = list(NewsSource.objects.filter(is_active=True))
        if db_sources:
            return db_sources
        sources_conf = RuntimeConfigService.get("NEWS_SOURCES", getattr(settings, "NEWS_SOURCES", []))
        resolved = []
        for source_conf in sources_conf:
            source, _ = NewsSource.objects.get_or_create(
                slug=source_conf["slug"],
                defaults={
                    "name": source_conf["name"],
                    "source_type": source_conf.get("source_type", NewsSource.SourceType.RSS),
                    "base_url": source_conf["base_url"],
                    "is_trusted": source_conf.get("is_trusted", False),
                    "reliability_score": source_conf.get("reliability_score", 0.5),
                    "config": source_conf.get("config", {}),
                },
            )
            resolved.append(source)
        return resolved

    def ingest(self, lookback_days: int | None = None) -> dict[str, int]:
        created_count = 0
        indexed_chunks = 0
        skipped_old_count = 0
        lookback_days = self._normalize_lookback_days(lookback_days)
        fresh_limit = timezone.now() - timedelta(days=lookback_days)
        sources = self._resolve_sources()
        rss_connector = RSSNewsConnector()
        api_connector = APINewsConnector(lookback_days=lookback_days)
        for source in sources:
            try:
                if source.source_type == NewsSource.SourceType.RSS:
                    items = rss_connector.fetch(source)
                elif source.source_type == NewsSource.SourceType.API:
                    items = api_connector.fetch(source)
                else:
                    continue
            except Exception as exc:
                logger.warning("Source fetch failed for %s: %s", source.slug, exc)
                continue
            for item in items:
                if item.published_at < fresh_limit:
                    skipped_old_count += 1
                    continue
                item_isins = extract_isins(f"{item.title} {item.summary} {item.content}")
                if item_isins:
                    item.metadata = {**item.metadata, "isins": item_isins}
                content_hash = self._hash_text(item.title, item.content)
                if NewsArticle.objects.filter(content_hash=content_hash).exists():
                    continue
                if item.url and NewsArticle.objects.filter(url=item.url).exists():
                    continue
                article = NewsArticle.objects.create(
                    source=source,
                    external_id=item.external_id,
                    url=item.url,
                    title=item.title,
                    summary=item.summary,
                    content=item.content,
                    language=item.language,
                    published_at=item.published_at,
                    content_hash=content_hash,
                    metadata=item.metadata,
                )
                created_count += 1
                entities = self.entity_extractor.extract(article)
                if entities:
                    NewsEntity.objects.bulk_create(entities)
                chunks = self._split_chunks(article.content)
                vectors = self.embedding_service.embed(chunks)
                model_name = self.embedding_service.model_name
                chunk_models = []
                points = []
                for idx, (chunk, vector) in enumerate(zip(chunks, vectors, strict=False)):
                    vector_id = hashlib.md5(f"{article.id}:{idx}:{model_name}".encode("utf-8")).hexdigest()
                    chunk_models.append(
                        NewsChunk(
                            article=article,
                            chunk_index=idx,
                            text=chunk,
                            embedding_model=model_name,
                            vector_id=vector_id,
                            metadata={"dim": len(vector)},
                        )
                    )
                    points.append(
                        {
                            "id": vector_id,
                            "vector": vector,
                            "payload": {
                                "article_id": article.id,
                                "chunk_index": idx,
                                "source_slug": article.source.slug,
                                "title": article.title,
                                "url": article.url,
                                "published_at": article.published_at.isoformat(),
                                "language": article.language,
                                "is_trusted": article.source.is_trusted,
                            },
                        }
                    )
                NewsChunk.objects.bulk_create(chunk_models)
                if points:
                    self.vector_store.upsert(points=points, vector_size=len(vectors[0]))
                    indexed_chunks += len(points)
        return {
            "created_articles": created_count,
            "sources": len(sources),
            "indexed_chunks": indexed_chunks,
            "skipped_old_articles": skipped_old_count,
            "lookback_days": lookback_days,
        }
