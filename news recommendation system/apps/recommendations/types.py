from dataclasses import dataclass

from apps.news.models import NewsArticle


@dataclass
class ScoredArticle:
    article: NewsArticle
    score: float
    breakdown: dict


@dataclass
class AssetMatcher:
    symbol: str
    name: str
    aliases: set[str]
    contextual_aliases: set[str]
    asset_type: str
    sector: str = ""
    exchange: str = ""
