import re
from html import unescape

from apps.news.models import NewsArticle
from apps.portfolios.aliases import build_asset_aliases, normalize_asset_text
from apps.portfolios.models import Asset


class EntityAliasMixin:
    @staticmethod
    def _normalize_text(value: str) -> str:
        return normalize_asset_text(value)

    def _load_assets(self) -> dict[str, list[Asset]]:
        assets: dict[str, list[Asset]] = {}
        queryset = Asset.objects.exclude(symbol="").only("symbol", "name", "exchange", "aliases")
        for asset in queryset:
            symbol = asset.symbol.strip().upper()
            if symbol:
                assets.setdefault(symbol, []).append(asset)
        return assets

    def _build_asset_aliases(self) -> dict[str, set[str]]:
        alias_map: dict[str, set[str]] = {}
        for symbol, assets in self.assets_by_symbol.items():
            aliases: set[str] = set()
            for asset in assets:
                aliases.update(
                    build_asset_aliases(
                        symbol=symbol,
                        name=asset.name,
                        exchange=asset.exchange,
                        aliases=asset.aliases,
                    )
                )
            if aliases:
                alias_map[symbol] = aliases
        return alias_map

    def _article_known_symbols(self, article: NewsArticle, text: str) -> set[str]:
        symbols: set[str] = set()
        metadata = article.metadata if isinstance(article.metadata, dict) else {}
        for raw_symbol in metadata.get("tickers") or []:
            symbol = str(raw_symbol).strip().upper()
            if symbol in self.assets_by_symbol:
                symbols.add(symbol)
        for match in self.TICKER_RE.findall(text):
            symbol = match.replace("$", "").strip().upper()
            if symbol in self.assets_by_symbol:
                symbols.add(symbol)
        return symbols

    @staticmethod
    def _clean_company_text(company_text: str) -> str:
        cleaned = unescape(re.sub(r"\s+", " ", company_text or ""))
        cleaned = re.sub(r"\s*[\(\[]\s*(?:[A-Z]+[:/])?\$?[A-Z]{1,5}\s*[\)\]]\s*", " ", cleaned)
        cleaned = cleaned.replace("«", "").replace("»", "")
        return cleaned.strip(" \"'.,;:-")

    @staticmethod
    def _company_has_explicit_symbol_pair(text: str, company_text: str, symbol: str) -> bool:
        company = re.escape(company_text.strip())
        if not company:
            return False
        ticker = rf"(?:[A-Z]+[:/])?\$?{re.escape(symbol)}"
        patterns = (
            rf"{company}\s*[\(\[]\s*{ticker}\s*[\)\]]",
            rf"\b{ticker}\s*[\(\[]\s*{company}\s*[\)\]]",
        )
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)

    def _can_learn_alias(self, article: NewsArticle, asset: Asset, company_text: str, text: str) -> bool:
        if article.source.config.get("technical_feed"):
            return False
        cleaned = self._clean_company_text(company_text)
        if len(cleaned) < 3 or len(cleaned) > self.MAX_LEARNED_ALIAS_LENGTH:
            return False
        normalized_company = self._normalize_text(cleaned)
        if not normalized_company:
            return False

        symbol = asset.symbol.strip().upper()
        aliases = self.asset_aliases.get(symbol, set())
        if normalized_company in aliases:
            return True

        return self._company_has_explicit_symbol_pair(text, cleaned, symbol)

    def _learn_asset_alias(self, asset: Asset, company_text: str) -> bool:
        cleaned = self._clean_company_text(company_text)
        normalized_company = self._normalize_text(cleaned)
        if not normalized_company:
            return False

        symbol = asset.symbol.strip().upper()
        aliases = list(asset.aliases or [])
        saved_aliases = {self._normalize_text(str(alias)) for alias in aliases}
        asset_name = re.sub(r"\s+", " ", asset.name or "").strip()
        is_base_value = cleaned.casefold() == asset_name.casefold() or cleaned.upper() == symbol
        if not is_base_value and normalized_company not in saved_aliases:
            aliases.append(cleaned)
            asset.aliases = aliases
            asset.save(update_fields=["aliases", "updated_at"])
            changed = True
        else:
            changed = False

        self.asset_aliases[symbol] = build_asset_aliases(
            symbol=symbol,
            name=asset.name,
            exchange=asset.exchange,
            aliases=asset.aliases,
        )
        return changed

    def _learn_alias_for_symbol(self, symbol: str, company_text: str) -> None:
        for asset in self.assets_by_symbol.get(symbol, []):
            self._learn_asset_alias(asset, company_text)
        aliases: set[str] = set()
        for asset in self.assets_by_symbol.get(symbol, []):
            aliases.update(
                build_asset_aliases(
                    symbol=symbol,
                    name=asset.name,
                    exchange=asset.exchange,
                    aliases=asset.aliases,
                )
            )
        if aliases:
            self.asset_aliases[symbol] = aliases

    @staticmethod
    def _match_asset_symbols(normalized_text: str, alias_map: dict[str, set[str]]) -> list[str]:
        haystack = f" {normalized_text} "
        matched = []
        for symbol, aliases in alias_map.items():
            symbol_token = symbol.lower()
            if f" {symbol_token} " in haystack:
                matched.append(symbol)
                continue
            if any(f" {alias} " in haystack for alias in aliases if alias and alias != symbol):
                matched.append(symbol)
        return matched


