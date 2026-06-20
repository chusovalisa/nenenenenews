import json
import logging
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)


@dataclass
class UnifiedNewsItem:
    external_id: str
    url: str
    title: str
    summary: str
    content: str
    published_at: datetime
    language: str = "ru"
    tickers: list[str] = field(default_factory=list)
    isins: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def parse_news_datetime(value: str | None) -> datetime:
    if not value:
        return timezone.now()
    cleaned = str(value).strip()
    if len(cleaned) == 13 and cleaned[8] == "T":
        try:
            parsed = datetime.strptime(cleaned, "%Y%m%dT%H%M").replace(tzinfo=dt_timezone.utc)
            return parsed.astimezone(timezone.get_current_timezone())
        except ValueError:
            pass
    parsed = parse_datetime(cleaned)
    if parsed is None:
        return timezone.now()
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, dt_timezone.utc)
    return parsed.astimezone(timezone.get_current_timezone())


class NewsAPIUnavailable(RuntimeError):
    pass


class BaseNewsAPIAdapter:
    name = "base"
    key_setting = ""
    api_key_header = ""
    auth_scheme = ""
    timeout_setting = "NEWS_API_TIMEOUT_SECONDS"

    def __init__(self, source, lookback_days: int | None = None) -> None:
        self.source = source
        self.config = source.config or {}
        self.api_key = str(self.config.get("api_key") or getattr(settings, self.key_setting, "") or "").strip()
        self.timeout = int(self.config.get("timeout_seconds") or getattr(settings, self.timeout_setting, 15))
        try:
            self.lookback_days = max(1, min(int(lookback_days or getattr(settings, "NEWS_LOOKBACK_DAYS", 1)), 365))
        except (TypeError, ValueError):
            self.lookback_days = max(1, int(getattr(settings, "NEWS_LOOKBACK_DAYS", 1)))

    def is_enabled(self) -> bool:
        if self.key_setting and not self.api_key:
            logger.warning("%s skipped: API key is not configured.", self.name)
            return False
        return True

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": "FinanceNews/1.0"}
        if self.api_key_header and self.api_key:
            if self.auth_scheme:
                headers[self.api_key_header] = f"{self.auth_scheme} {self.api_key}"
            else:
                headers[self.api_key_header] = self.api_key
        return headers

    def _fresh_limit(self) -> datetime:
        return timezone.now() - timedelta(days=self.lookback_days)

    @staticmethod
    def _ssl_context() -> ssl.SSLContext:
        try:
            import certifi

            return ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            return ssl.create_default_context()

    def _fetch_json(self, url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        request = Request(url, headers=headers or self._headers())
        try:
            with urlopen(request, timeout=self.timeout, context=self._ssl_context()) as response:
                status = getattr(response, "status", 200)
                if status == 429:
                    raise NewsAPIUnavailable(f"{self.name} rate limit exceeded")
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            logger.warning("%s fetch failed: %s", self.name, exc)
            raise NewsAPIUnavailable(str(exc)) from exc

    def fetch(self) -> list[UnifiedNewsItem]:
        raise NotImplementedError


class NewsAPIAdapter(BaseNewsAPIAdapter):
    name = "newsapi"
    key_setting = "NEWSAPI_KEY"
    api_key_header = "X-Api-Key"

    def fetch(self) -> list[UnifiedNewsItem]:
        if not self.is_enabled():
            return []
        query = self.config.get("query", "finance OR stocks OR рынок OR акции")
        params = {
            "q": query,
            "language": self.config.get("language", "ru"),
            "sortBy": self.config.get("sort_by", "publishedAt"),
            "pageSize": int(self.config.get("page_size", 50)),
            "from": self._fresh_limit().date().isoformat(),
        }
        payload = self._fetch_json(f"{self.source.base_url}?{urlencode(params)}")
        if payload.get("status") == "error":
            logger.warning("newsapi returned error: %s", payload.get("message"))
            return []
        output = []
        for item in payload.get("articles", []) or []:
            title = item.get("title") or ""
            url = item.get("url") or ""
            if not title or not url:
                continue
            summary = item.get("description") or ""
            content = item.get("content") or summary or title
            source_name = (item.get("source") or {}).get("name") or self.source.name
            output.append(
                UnifiedNewsItem(
                    external_id=url,
                    url=url,
                    title=title,
                    summary=summary,
                    content=content,
                    published_at=parse_news_datetime(item.get("publishedAt")),
                    language=params["language"],
                    metadata={"provider": self.name, "source_name": source_name},
                )
            )
        return output


class FinnhubNewsAdapter(BaseNewsAPIAdapter):
    name = "finnhub"
    key_setting = "FINNHUB_API_KEY"

    def fetch(self) -> list[UnifiedNewsItem]:
        if not self.is_enabled():
            return []
        params = {
            "category": self.config.get("category", "general"),
            "token": self.api_key,
        }
        payload = self._fetch_json(f"{self.source.base_url}?{urlencode(params)}", headers={"User-Agent": "FinanceNews/1.0"})
        output = []
        for item in payload if isinstance(payload, list) else []:
            title = item.get("headline") or ""
            url = item.get("url") or ""
            if not title or not url:
                continue
            published_at = datetime.fromtimestamp(int(item.get("datetime") or 0), tz=dt_timezone.utc)
            output.append(
                UnifiedNewsItem(
                    external_id=str(item.get("id") or url),
                    url=url,
                    title=title,
                    summary=item.get("summary") or "",
                    content=item.get("summary") or title,
                    published_at=published_at.astimezone(timezone.get_current_timezone()),
                    language=self.config.get("language", "en"),
                    metadata={"provider": self.name, "category": params["category"]},
                )
            )
        return output


class AlphaVantageNewsAdapter(BaseNewsAPIAdapter):
    name = "alpha_vantage"
    key_setting = "ALPHA_VANTAGE_API_KEY"

    def fetch(self) -> list[UnifiedNewsItem]:
        if not self.is_enabled():
            return []
        params = {
            "function": "NEWS_SENTIMENT",
            "apikey": self.api_key,
            "limit": int(self.config.get("limit", 50)),
            "time_from": self._fresh_limit().strftime("%Y%m%dT%H%M"),
        }
        tickers = self.config.get("tickers")
        if tickers:
            params["tickers"] = tickers
        topics = self.config.get("topics")
        if topics:
            params["topics"] = topics
        payload = self._fetch_json(f"{self.source.base_url}?{urlencode(params)}", headers={"User-Agent": "FinanceNews/1.0"})
        if payload.get("Note") or payload.get("Information"):
            logger.warning("alpha_vantage skipped: %s", payload.get("Note") or payload.get("Information"))
            return []
        output = []
        for item in payload.get("feed", []) or []:
            title = item.get("title") or ""
            url = item.get("url") or ""
            if not title or not url:
                continue
            tickers_payload = item.get("ticker_sentiment") or []
            tickers_out = [str(t.get("ticker", "")).split(":")[-1].upper() for t in tickers_payload if t.get("ticker")]
            output.append(
                UnifiedNewsItem(
                    external_id=url,
                    url=url,
                    title=title,
                    summary=item.get("summary") or "",
                    content=item.get("summary") or title,
                    published_at=parse_news_datetime(item.get("time_published")),
                    language=self.config.get("language", "en"),
                    tickers=tickers_out,
                    metadata={"provider": self.name, "source_name": item.get("source")},
                )
            )
        return output


class MarketauxNewsAdapter(BaseNewsAPIAdapter):
    name = "marketaux"
    key_setting = "MARKETAUX_API_KEY"

    def fetch(self) -> list[UnifiedNewsItem]:
        if not self.is_enabled():
            return []
        params = {
            "api_token": self.api_key,
            "language": self.config.get("language", "en"),
            "limit": int(self.config.get("limit", 50)),
            "published_after": self._fresh_limit().isoformat(),
        }
        countries = self.config.get("countries")
        if countries:
            params["countries"] = countries
        symbols = self.config.get("symbols")
        if symbols:
            params["symbols"] = symbols
        payload = self._fetch_json(f"{self.source.base_url}?{urlencode(params)}", headers={"User-Agent": "FinanceNews/1.0"})
        output = []
        for item in payload.get("data", []) or []:
            title = item.get("title") or ""
            url = item.get("url") or ""
            if not title or not url:
                continue
            entities = item.get("entities") or []
            tickers = [str(entity.get("symbol", "")).split(".")[0].upper() for entity in entities if entity.get("symbol")]
            output.append(
                UnifiedNewsItem(
                    external_id=str(item.get("uuid") or url),
                    url=url,
                    title=title,
                    summary=item.get("description") or "",
                    content=item.get("snippet") or item.get("description") or title,
                    published_at=parse_news_datetime(item.get("published_at")),
                    language=params["language"],
                    tickers=tickers,
                    metadata={"provider": self.name, "source_name": item.get("source")},
                )
            )
        return output


class GNewsAdapter(BaseNewsAPIAdapter):
    name = "gnews"
    key_setting = "GNEWS_API_KEY"

    def fetch(self) -> list[UnifiedNewsItem]:
        if not self.is_enabled():
            return []
        params = {
            "q": self.config.get("query", "finance OR stocks OR рынок OR акции"),
            "lang": self.config.get("language", "ru"),
            "max": int(self.config.get("limit", 50)),
            "apikey": self.api_key,
            "from": self._fresh_limit().isoformat(),
        }
        payload = self._fetch_json(f"{self.source.base_url}?{urlencode(params)}", headers={"User-Agent": "FinanceNews/1.0"})
        output = []
        for item in payload.get("articles", []) or []:
            title = item.get("title") or ""
            url = item.get("url") or ""
            if not title or not url:
                continue
            source_name = (item.get("source") or {}).get("name") or self.source.name
            output.append(
                UnifiedNewsItem(
                    external_id=url,
                    url=url,
                    title=title,
                    summary=item.get("description") or "",
                    content=item.get("content") or item.get("description") or title,
                    published_at=parse_news_datetime(item.get("publishedAt")),
                    language=params["lang"],
                    metadata={"provider": self.name, "source_name": source_name},
                )
            )
        return output


API_ADAPTERS = {
    "newsapi": NewsAPIAdapter,
    "finnhub_market_news": FinnhubNewsAdapter,
    "alpha_vantage_news_sentiment": AlphaVantageNewsAdapter,
    "marketaux": MarketauxNewsAdapter,
    "gnews": GNewsAdapter,
}
