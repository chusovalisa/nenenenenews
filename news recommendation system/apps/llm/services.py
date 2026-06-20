import http.client
import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings

from apps.core.services import RuntimeConfigService
from apps.llm.models import LLMClaim, LLMProvider, LLMResponse
from apps.news.models import NewsArticle
from apps.portfolios.aliases import build_asset_aliases
from apps.portfolios.models import Portfolio

logger = logging.getLogger(__name__)


@dataclass
class LLMOutput:
    localized_title: str
    summary: str
    impact_analysis: str
    raw_text: str
    model_name: str
    metadata: dict[str, Any] | None = None



class LocalHeuristicLLM:
    model_name = "local-heuristic-v1"

    @staticmethod
    def _is_probably_english(text: str) -> bool:
        letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text or "")
        if not letters:
            return False
        latin = sum(1 for char in letters if "a" <= char.lower() <= "z")
        return latin / max(len(letters), 1) > 0.65

    @staticmethod
    def _topic_hint(article: NewsArticle) -> str:
        text = f"{article.title} {article.summary} {article.content}".lower()
        hints = []
        if "buyback" in text or "share repurchase" in text:
            hints.append("выкуп акций")
        if "ai" in text or "artificial intelligence" in text:
            hints.append("расходы на искусственный интеллект")
        if "cash" in text or "capital expenditure" in text or "capex" in text:
            hints.append("денежный поток и капитальные расходы")
        if "dividend" in text:
            hints.append("дивиденды")
        if "earnings" in text or "revenue" in text or "profit" in text:
            hints.append("финансовые результаты")
        return ", ".join(hints[:3])

    @classmethod
    def _relation_reason(cls, article: NewsArticle, symbol: str, aliases: set[str]) -> str:
        fields = (
            ("заголовке", article.title or ""),
            ("описании", article.summary or ""),
            ("тексте", article.content[:1500] or ""),
        )
        for place, value in fields:
            lowered = value.lower()
            for alias in {symbol, *aliases}:
                if alias.lower() in lowered:
                    return f"в {place} прямо упоминается {alias}"
        return "найдено прямое совпадение с активом или его эмитентом"

    @classmethod
    def _build_relation_text(cls, article: NewsArticle, asset_aliases: dict[str, set[str]]) -> str:
        symbols = list(asset_aliases.keys())
        if not symbols:
            return "Связь с активами портфеля не определена."
        if len(symbols) == 1:
            symbol = symbols[0]
            return f"Связь с {symbol}: {cls._relation_reason(article, symbol, asset_aliases[symbol])}."
        parts = [f"{symbol}: {cls._relation_reason(article, symbol, asset_aliases[symbol])}" for symbol in symbols]
        return f"Связь с {', '.join(symbols)}: " + "; ".join(parts) + "."

    @staticmethod
    def _build_localized_title(article: NewsArticle) -> str:
        title = (article.title or "").strip()
        if not title:
            return "Новость без заголовка"
        if not LocalHeuristicLLM._is_probably_english(title):
            return title
        return "Англоязычная новость по выбранному активу"

    @staticmethod
    def _build_summary(article: NewsArticle) -> str:
        source = (article.summary or article.content or article.title or "").strip()
        source = re.sub(r"\s+", " ", source)
        source = re.sub(r"\.{2,}", ".", source)
        if not source:
            return article.title
        if LocalHeuristicLLM._is_probably_english(source):
            hint = LocalHeuristicLLM._topic_hint(article)
            if hint:
                return f"Англоязычный источник сообщает о теме: {hint}."
            return "Англоязычный источник сообщает о событии, связанном с выбранным активом."

        sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", source) if item.strip()]
        filtered = []
        for sentence in sentences:
            if "..." in sentence:
                continue
            if "Наименование эмитента" in sentence or "Идентификационный/Регистрационный номер" in sentence:
                continue
            filtered.append(sentence)
            if len(filtered) == 2:
                break
        if filtered:
            return " ".join(filtered)[:500]

        title = article.title.strip()
        date_match = re.search(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b", article.content)
        if "Список ценных бумаг" in title:
            suffix = f" от {date_match.group(0)}" if date_match else ""
            return f"{title}{suffix}. Московская биржа опубликовала служебное сообщение об изменении статуса ценных бумаг."
        return (source[:500].rsplit(" ", 1)[0].rstrip(".") + ".") if len(source) > 500 else source

    def generate(self, article: NewsArticle, portfolio: Portfolio, matched_symbols: list[str] | None = None) -> LLMOutput:
        symbols = matched_symbols or sorted({p.asset.symbol for p in portfolio.positions.select_related("asset")})
        positions = list(portfolio.positions.select_related("asset"))
        asset_aliases = {
            position.asset.symbol.upper(): build_asset_aliases(
                position.asset.symbol,
                position.asset.name,
                aliases=position.asset.aliases,
            )
            for position in positions
            if position.asset.symbol.upper() in symbols
        }
        localized_title = self._build_localized_title(article)
        summary = self._build_summary(article)
        topic_hint = self._topic_hint(article)
        impact = self._build_relation_text(article, asset_aliases)
        if topic_hint:
            impact += f" Возможное влияние нужно оценивать через {topic_hint}."
        impact = (
            f"{impact} Не делайте инвестиционный вывод без проверки первоисточника."
        )
        raw = f"TITLE:\n{localized_title}\n\nSUMMARY:\n{summary}\n\nIMPACT:\n{impact}"
        return LLMOutput(
            localized_title=localized_title,
            summary=summary,
            impact_analysis=impact,
            raw_text=raw,
            model_name=self.model_name,
        )


class OllamaLLM:
    def __init__(self, model_name: str, base_url: str, timeout_seconds: int) -> None:
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _build_prompt(self, article: NewsArticle, portfolio: Portfolio, matched_symbols: list[str] | None = None) -> str:
        symbols = matched_symbols or sorted(position.asset.symbol for position in portfolio.positions.select_related("asset"))
        return (
            "Ты финансовый ассистент для русскоязычного интерфейса.\n"
            "Отвечай только на русском языке.\n"
            "Верни строго JSON-объект с ключами localized_title, summary и impact_analysis.\n"
            "Не добавляй markdown, комментарии, вступления, английский текст и лишние поля.\n"
            "Если статья на английском, переведи смысл на русский; не копируй английские фразы в localized_title, summary и impact_analysis.\n"
            "Не выдумывай факты, которых нет в статье.\n"
            "Сохраняй тикеры, даты, время, проценты и числовые значения в исходном виде.\n"
            "localized_title: короткий русский заголовок карточки, до 90 символов, без кавычек вокруг всего текста.\n"
            "summary: 1-2 коротких предложения только по сути новости. "
            "В summary нельзя писать оценку влияния вроде 'положительно влияет' или 'негативно влияет', если это не прямой факт из статьи.\n"
            "impact_analysis: 1-2 коротких предложения о возможном влиянии на портфель. "
            "Обязательно начни impact_analysis с фразы 'Связь с <тикер>:' и объясни, почему статья относится именно к этому активу. "
            "Анализируй влияние только на тикеры, к которым отнесена эта новость; не перечисляй остальные тикеры портфеля. "
            "Если прямое влияние не следует из текста, напиши нейтрально и без домыслов.\n"
            f"Название портфеля: {portfolio.name}\n"
            f"Тикеры этой новости: {', '.join(symbols) if symbols else 'не указаны'}\n"
            f"Заголовок статьи: {article.title}\n"
            f"Краткое описание статьи: {article.summary}\n"
            f"Текст статьи: {article.content[:6000]}\n"
        )

    @staticmethod
    def _extract_json(text: str) -> dict:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))

    @staticmethod
    def _summary_format() -> dict:
        return {
            "type": "object",
            "properties": {
                "localized_title": {"type": "string"},
                "summary": {"type": "string"},
                "impact_analysis": {"type": "string"},
            },
            "required": ["localized_title", "summary", "impact_analysis"],
        }

    def _chat(self, messages: list[dict[str, str]], response_format: dict | None = None) -> str:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0,
                "seed": 42,
            },
        }
        if response_format:
            payload["format"] = response_format

        parsed_url = urlsplit(self.base_url)
        connection_cls = http.client.HTTPSConnection if parsed_url.scheme == "https" else http.client.HTTPConnection
        host = parsed_url.hostname or "127.0.0.1"
        port = parsed_url.port
        base_path = parsed_url.path.rstrip("/")
        path = f"{base_path}/api/chat" if base_path else "/api/chat"
        connection = None
        try:
            connection = connection_cls(host, port=port, timeout=self.timeout_seconds)
            connection.request(
                "POST",
                path,
                body=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "FinanceNews/1.0"},
            )
            response = connection.getresponse()
            response_body = response.read().decode("utf-8", errors="replace")
            if response.status >= 400:
                raise RuntimeError(f"Ollama request failed: HTTP {response.status}: {response_body or response.reason}")
            body = json.loads(response_body)
        except (OSError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

        return body.get("message", {}).get("content", "").strip()

    @staticmethod
    def _validate_output(
        localized_title: str,
        summary: str,
        impact_analysis: str,
        matched_symbols: list[str] | None = None,
    ) -> None:
        text = " ".join([localized_title, summary, impact_analysis])
        if re.search(r"[\u4e00-\u9fff]", text):
            raise RuntimeError("LLM response contains non-Russian CJK text.")

        allowed_symbols = {symbol.strip().upper() for symbol in matched_symbols or [] if symbol.strip()}
        if not allowed_symbols:
            return

        ignored_tokens = {"JSON", "HTTP", "API", "LLM", "USD", "EUR", "RUB", "ETF", "CEO", "CFO"}
        output_tickers = {
            token.upper()
            for token in re.findall(r"\b[A-Z]{2,5}\b", text)
            if token.upper() not in ignored_tokens
        }
        unexpected_tickers = output_tickers - allowed_symbols
        if unexpected_tickers:
            raise RuntimeError(f"LLM response contains unrelated ticker(s): {sorted(unexpected_tickers)}")

        expected_prefixes = tuple(f"Связь с {symbol}:" for symbol in sorted(allowed_symbols))
        if expected_prefixes and not impact_analysis.startswith(expected_prefixes):
            raise RuntimeError("LLM impact_analysis does not start with a matched ticker.")

    def generate(self, article: NewsArticle, portfolio: Portfolio, matched_symbols: list[str] | None = None) -> LLMOutput:
        content = self._chat(
            [
                {
                    "role": "user",
                    "content": self._build_prompt(article=article, portfolio=portfolio, matched_symbols=matched_symbols),
                }
            ],
            response_format=self._summary_format(),
        )
        parsed = self._extract_json(content)
        localized_title = parsed.get("localized_title", "").strip() or LocalHeuristicLLM._build_localized_title(article)
        summary = parsed.get("summary", "").strip()
        impact_analysis = parsed.get("impact_analysis", "").strip()
        self._validate_output(localized_title, summary, impact_analysis, matched_symbols=matched_symbols)
        raw = json.dumps(parsed, ensure_ascii=False)
        return LLMOutput(
            localized_title=localized_title[:600],
            summary=summary,
            impact_analysis=impact_analysis,
            raw_text=raw,
            model_name=self.model_name,
        )



class LLMService:
    def __init__(self) -> None:
        self.prompt_version = RuntimeConfigService.get("PROMPT_VERSION", "v1")
        self.ollama_base_url = RuntimeConfigService.get("OLLAMA_BASE_URL", settings.OLLAMA_BASE_URL)
        self.ollama_model = RuntimeConfigService.get("OLLAMA_MODEL", settings.OLLAMA_MODEL)
        self.ollama_council_models = self._normalize_model_list(
            RuntimeConfigService.get("OLLAMA_COUNCIL_MODELS", settings.OLLAMA_COUNCIL_MODELS)
        )
        self.ollama_council_judge_model = RuntimeConfigService.get(
            "OLLAMA_COUNCIL_JUDGE_MODEL",
            settings.OLLAMA_COUNCIL_JUDGE_MODEL,
        )
        self.ollama_fallback_model = RuntimeConfigService.get(
            "OLLAMA_FALLBACK_MODEL",
            getattr(settings, "OLLAMA_FALLBACK_MODEL", ""),
        )
        self.ollama_timeout_seconds = RuntimeConfigService.get(
            "OLLAMA_TIMEOUT_SECONDS",
            settings.OLLAMA_TIMEOUT_SECONDS,
        )

    @staticmethod
    def _normalize_model_list(raw_models: Any) -> list[str]:
        if isinstance(raw_models, str):
            try:
                parsed = json.loads(raw_models)
                if isinstance(parsed, list):
                    raw_models = parsed
                else:
                    raw_models = raw_models.split(",")
            except json.JSONDecodeError:
                raw_models = raw_models.split(",")
        if not isinstance(raw_models, list):
            return []
        normalized = []
        for model_name in raw_models:
            cleaned = str(model_name).strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized

    def _provider_primary_model(self, provider: LLMProvider | None) -> str:
        if provider and provider.provider_type == LLMProvider.ProviderType.OLLAMA:
            return str(provider.model_name or self.ollama_model or "").strip()
        if not provider:
            return str(self.ollama_model or "").strip()
        return ""

    def _provider_council_models(self, provider: LLMProvider | None) -> list[str]:
        if provider and provider.provider_type != LLMProvider.ProviderType.OLLAMA:
            return []
        if not provider:
            advisor_models = self.ollama_council_models
        else:
            provider_models = self._normalize_model_list(provider.config.get("council_models", []))
            advisor_models = provider_models or self.ollama_council_models
        if not advisor_models:
            return []
        return self._normalize_model_list([self._provider_primary_model(provider), *advisor_models])

    def _provider_judge_model(self, provider: LLMProvider | None, council_models: list[str]) -> str:
        if provider and provider.provider_type == LLMProvider.ProviderType.OLLAMA:
            configured = str(provider.config.get("judge_model", "")).strip()
            if configured:
                return configured
        configured = str(self.ollama_council_judge_model or "").strip()
        return configured or (provider.model_name if provider else "") or self.ollama_model or (council_models[0] if council_models else "")

    def _provider_fallback_model(self, provider: LLMProvider | None) -> str:
        if provider and provider.provider_type == LLMProvider.ProviderType.OLLAMA:
            configured = str(provider.config.get("fallback_model", "")).strip()
            if configured:
                return configured
        return str(self.ollama_fallback_model or "").strip()

    def _provider_base_url(self, provider: LLMProvider | None) -> str:
        if provider and provider.provider_type == LLMProvider.ProviderType.OLLAMA:
            configured = str(provider.config.get("base_url", "")).strip()
            if configured:
                return configured
        return self.ollama_base_url

    def _resolve_provider(self) -> LLMProvider | None:
        return LLMProvider.objects.filter(is_active=True).first()

    def _resolve_effective_model_name(self, provider: LLMProvider | None) -> str:
        from apps.llm.council import OllamaCouncilLLM

        council_models = self._provider_council_models(provider)
        if council_models:
            judge_model = self._provider_judge_model(provider, council_models)
            return OllamaCouncilLLM(
                model_names=council_models,
                judge_model_name=judge_model,
                base_url=self.ollama_base_url,
                timeout_seconds=int(self.ollama_timeout_seconds),
            ).effective_model_name
        if provider and provider.provider_type == LLMProvider.ProviderType.OLLAMA:
            return provider.model_name or self.ollama_model or LocalHeuristicLLM.model_name
        if not provider and self.ollama_model:
            return self.ollama_model
        return LocalHeuristicLLM.model_name

    def _generate_with_provider(
        self,
        article: NewsArticle,
        portfolio: Portfolio,
        provider: LLMProvider | None,
        matched_symbols: list[str] | None = None,
    ) -> LLMOutput:
        try:
            council_models = self._provider_council_models(provider)
            if council_models:
                from apps.llm.council import OllamaCouncilLLM

                judge_model = self._provider_judge_model(provider, council_models)
                return OllamaCouncilLLM(
                    model_names=council_models,
                    judge_model_name=judge_model,
                    base_url=self._provider_base_url(provider),
                    timeout_seconds=int(self.ollama_timeout_seconds),
                ).generate(article, portfolio, matched_symbols=matched_symbols)
            if provider and provider.provider_type == LLMProvider.ProviderType.OLLAMA:
                model_name = provider.model_name or self.ollama_model
                if not model_name:
                    raise RuntimeError("Ollama provider is active but model_name is empty.")
                return OllamaLLM(
                    model_name=model_name,
                    base_url=self._provider_base_url(provider),
                    timeout_seconds=int(self.ollama_timeout_seconds),
                ).generate(article, portfolio, matched_symbols=matched_symbols)
            if not provider and self.ollama_model:
                return OllamaLLM(
                    model_name=self.ollama_model,
                    base_url=self.ollama_base_url,
                    timeout_seconds=int(self.ollama_timeout_seconds),
                ).generate(article, portfolio, matched_symbols=matched_symbols)
        except RuntimeError as exc:
            logger.warning("LLM provider failed: %s", exc)
            fallback_model = self._provider_fallback_model(provider)
            if fallback_model:
                try:
                    return OllamaLLM(
                        model_name=fallback_model,
                        base_url=self._provider_base_url(provider),
                        timeout_seconds=int(self.ollama_timeout_seconds),
                    ).generate(article, portfolio, matched_symbols=matched_symbols)
                except RuntimeError as fallback_exc:
                    logger.warning("LLM fallback model %s failed, heuristic used: %s", fallback_model, fallback_exc)
        if not provider or provider.provider_type == LLMProvider.ProviderType.LOCAL:
            return LocalHeuristicLLM().generate(article, portfolio, matched_symbols=matched_symbols)
        return LocalHeuristicLLM().generate(article, portfolio, matched_symbols=matched_symbols)

    @staticmethod
    def _extract_claims(summary: str) -> list[tuple[str, str]]:
        protected = str(summary or "")
        abbreviations = {
            "Corp.": "Corp",
            "Inc.": "Inc",
            "Ltd.": "Ltd",
            "Co.": "Co",
            "ПАО.": "ПАО",
            "АО.": "АО",
        }
        for source, replacement in abbreviations.items():
            protected = protected.replace(source, replacement)
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", protected) if s.strip()]
        claims = []
        for sentence in sentences[:8]:
            if len(sentence) < 20:
                continue
            if "..." in sentence:
                continue
            if sentence.startswith("("):
                continue
            if "Наименование эмитента" in sentence or "Идентификационный/Регистрационный номер" in sentence:
                continue
            if re.search(r"\b\d+\s*\.\s*$", sentence):
                continue
            if len(re.findall(r"[A-Za-zА-Яа-яЁё]{2,}", sentence)) < 4:
                continue
            claim_type = LLMClaim.ClaimType.NUMERIC if re.search(r"\d", sentence) else LLMClaim.ClaimType.EVENT
            claims.append((sentence, claim_type))
        return claims

    @staticmethod
    def _normalize_symbols(symbols: list[str] | None) -> list[str]:
        normalized = []
        for symbol in symbols or []:
            cleaned = str(symbol).strip().upper()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized

    def _ensure_claims(self, response: LLMResponse) -> None:
        if response.claims.exists():
            return
        LLMClaim.objects.bulk_create(
            [
                LLMClaim(response=response, claim_text=claim_text, claim_type=claim_type)
                for claim_text, claim_type in self._extract_claims(response.summary)
            ]
        )

    def summarize_article(
        self,
        user,
        portfolio: Portfolio,
        article: NewsArticle,
        matched_symbols: list[str] | None = None,
    ) -> LLMResponse:
        provider = self._resolve_provider()
        effective_model_name = self._resolve_effective_model_name(provider)
        matched_symbols = self._normalize_symbols(matched_symbols)
        cached_response = (
            LLMResponse.objects.filter(
                user=user,
                portfolio=portfolio,
                article=article,
                prompt_version=self.prompt_version,
                model_name=effective_model_name,
                input_payload__matched_symbols=matched_symbols,
            )
            .prefetch_related("claims")
            .first()
        )
        if cached_response:
            self._ensure_claims(cached_response)
            return cached_response

        output = self._generate_with_provider(article, portfolio, provider, matched_symbols=matched_symbols)
        response = LLMResponse.objects.create(
            user=user,
            portfolio=portfolio,
            article=article,
            provider=provider,
            prompt_version=self.prompt_version,
            model_name=output.model_name,
            input_payload={
                "article_id": article.id,
                "portfolio_id": portfolio.id,
                "matched_symbols": matched_symbols,
                "llm": output.metadata or {"mode": "single"},
            },
            raw_text=output.raw_text,
            summary=output.summary,
            localized_title=output.localized_title,
            impact_analysis=output.impact_analysis,
            token_usage={},
        )
        self._ensure_claims(response)
        return response
