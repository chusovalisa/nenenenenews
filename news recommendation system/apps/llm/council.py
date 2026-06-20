import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from apps.news.models import NewsArticle
from apps.portfolios.models import Portfolio
from apps.llm.services import LLMOutput, LocalHeuristicLLM, OllamaLLM

logger = logging.getLogger(__name__)


@dataclass
class CouncilCandidate:
    model_name: str
    localized_title: str = ""
    summary: str = ""
    impact_analysis: str = ""
    raw_text: str = ""
    error: str = ""

    @property
    def is_successful(self) -> bool:
        return bool(self.summary or self.impact_analysis) and not self.error


@dataclass
class CouncilReview:
    reviewer_model: str
    raw_text: str = ""
    error: str = ""

class OllamaCouncilLLM:
    def __init__(
        self,
        model_names: list[str],
        judge_model_name: str,
        base_url: str,
        timeout_seconds: int,
    ) -> None:
        self.model_names = self._normalize_models(model_names)
        self.judge_model_name = judge_model_name or (self.model_names[0] if self.model_names else "")
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _normalize_models(model_names: list[str]) -> list[str]:
        normalized = []
        for model_name in model_names:
            cleaned = str(model_name).strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized

    @staticmethod
    def _format_candidate_answers(candidates: list[CouncilCandidate], include_model_names: bool = False) -> str:
        blocks = []
        for index, candidate in enumerate(candidates, start=1):
            title = f"Вариант {index}"
            if include_model_names:
                title = f"{title} ({candidate.model_name})"
            blocks.append(
                "\n".join(
                    [
                        title,
                        f"localized_title: {candidate.localized_title}",
                        f"summary: {candidate.summary}",
                        f"impact_analysis: {candidate.impact_analysis}",
                    ]
                )
            )
        return "\n\n".join(blocks)

    @staticmethod
    def _format_reviews(reviews: list[CouncilReview]) -> str:
        output = []
        for review in reviews:
            if review.error:
                output.append(f"{review.reviewer_model}: ERROR: {review.error}")
            else:
                output.append(f"{review.reviewer_model}: {review.raw_text}")
        return "\n\n".join(output) if output else "Оценок нет."

    def _client(self, model_name: str) -> OllamaLLM:
        return OllamaLLM(
            model_name=model_name,
            base_url=self.base_url,
            timeout_seconds=self.timeout_seconds,
        )

    def _generate_candidate(
        self,
        model_name: str,
        article: NewsArticle,
        portfolio: Portfolio,
        matched_symbols: list[str] | None = None,
    ) -> CouncilCandidate:
        try:
            output = self._client(model_name).generate(article=article, portfolio=portfolio, matched_symbols=matched_symbols)
            return CouncilCandidate(
                model_name=model_name,
                localized_title=output.localized_title,
                summary=output.summary,
                impact_analysis=output.impact_analysis,
                raw_text=output.raw_text,
            )
        except Exception as exc:
            logger.warning("Council candidate %s failed: %s", model_name, exc)
            return CouncilCandidate(model_name=model_name, error=str(exc))

    def _review_candidates(
        self,
        reviewer_model: str,
        article: NewsArticle,
        portfolio: Portfolio,
        candidates: list[CouncilCandidate],
        matched_symbols: list[str] | None = None,
    ) -> CouncilReview:
        reviewed = [candidate for candidate in candidates if candidate.model_name != reviewer_model]
        if not reviewed:
            return CouncilReview(reviewer_model=reviewer_model, raw_text="Нет других ответов для оценки.")

        prompt = (
            "Ты участник совета LLM для финансового дайджеста.\n"
            "Пиши только на русском языке.\n"
            "Оцени анонимные варианты ответов других моделей по точности, полноте и осторожности.\n"
            "Не добавляй новые факты и не выдумывай влияние на портфель.\n"
            "Верни короткий JSON с ключами best_variant, useful_points, risks.\n"
            f"Название портфеля: {portfolio.name}\n"
            f"Тикеры этой новости: {', '.join(matched_symbols or []) if matched_symbols else 'не указаны'}\n"
            f"Заголовок статьи: {article.title}\n"
            f"Краткое описание статьи: {article.summary}\n"
            f"Текст статьи: {article.content[:6000]}\n\n"
            f"Варианты для оценки:\n{self._format_candidate_answers(reviewed)}"
        )
        try:
            raw_text = self._client(reviewer_model)._chat(
                [{"role": "user", "content": prompt}],
                response_format={
                    "type": "object",
                    "properties": {
                        "best_variant": {"type": "string"},
                        "useful_points": {"type": "string"},
                        "risks": {"type": "string"},
                    },
                    "required": ["best_variant", "useful_points", "risks"],
                },
            )
            return CouncilReview(reviewer_model=reviewer_model, raw_text=raw_text)
        except Exception as exc:
            logger.warning("Council reviewer %s failed: %s", reviewer_model, exc)
            return CouncilReview(reviewer_model=reviewer_model, error=str(exc))

    def _finalize(
        self,
        article: NewsArticle,
        portfolio: Portfolio,
        candidates: list[CouncilCandidate],
        reviews: list[CouncilReview],
        matched_symbols: list[str] | None = None,
    ) -> LLMOutput:
        prompt = (
            "Ты главная модель-судья в совете LLM для русскоязычного финансового дайджеста.\n"
            "У тебя есть исходная статья, варианты ответов моделей и их взаимные оценки.\n"
            "Собери лучший итоговый ответ: фактический, короткий, без домыслов и только на русском.\n"
            "Верни строго JSON-объект с ключами localized_title, summary и impact_analysis.\n"
            "Если статья на английском, переведи смысл на русский; не копируй английские фразы в localized_title, summary и impact_analysis.\n"
            "localized_title: короткий русский заголовок карточки, до 90 символов.\n"
            "summary: 1-2 коротких предложения по сути новости. "
            "В summary нельзя писать оценку влияния вроде 'положительно влияет' или 'негативно влияет', если это не прямой факт из статьи.\n"
            "impact_analysis: 1-2 коротких предложения о возможном влиянии только на тикеры этой новости. "
            "Обязательно начни impact_analysis с фразы 'Связь с <тикер>:' и объясни, почему статья относится именно к этому активу. "
            "Если прямого влияния нет, напиши нейтрально.\n"
            f"Название портфеля: {portfolio.name}\n"
            f"Тикеры этой новости: {', '.join(matched_symbols or []) if matched_symbols else 'не указаны'}\n"
            f"Заголовок статьи: {article.title}\n"
            f"Краткое описание статьи: {article.summary}\n"
            f"Текст статьи: {article.content[:6000]}\n\n"
            f"Ответы моделей:\n{self._format_candidate_answers(candidates, include_model_names=True)}\n\n"
            f"Оценки моделей:\n{self._format_reviews(reviews)}"
        )
        content = self._client(self.judge_model_name)._chat(
            [{"role": "user", "content": prompt}],
            response_format=OllamaLLM._summary_format(),
        )
        parsed = OllamaLLM._extract_json(content)
        localized_title = parsed.get("localized_title", "").strip() or LocalHeuristicLLM._build_localized_title(article)
        summary = parsed.get("summary", "").strip()
        impact_analysis = parsed.get("impact_analysis", "").strip()
        raw = json.dumps(parsed, ensure_ascii=False)
        return LLMOutput(
            localized_title=localized_title[:600],
            summary=summary,
            impact_analysis=impact_analysis,
            raw_text=raw,
            model_name=self.effective_model_name,
        )

    @property
    def effective_model_name(self) -> str:
        models = "+".join(self.model_names)
        return f"ollama-council:{models}->judge:{self.judge_model_name}"

    def generate(self, article: NewsArticle, portfolio: Portfolio, matched_symbols: list[str] | None = None) -> LLMOutput:
        if not self.model_names:
            raise RuntimeError("Ollama council is enabled but model list is empty.")

        with ThreadPoolExecutor(max_workers=min(len(self.model_names), 4)) as executor:
            futures = [
                executor.submit(self._generate_candidate, model_name, article, portfolio, matched_symbols)
                for model_name in self.model_names
            ]
            candidates = [future.result() for future in as_completed(futures)]

        successful_candidates = [candidate for candidate in candidates if candidate.is_successful]
        if not successful_candidates:
            errors = {candidate.model_name: candidate.error for candidate in candidates}
            raise RuntimeError(f"All Ollama council candidates failed: {errors}")

        with ThreadPoolExecutor(max_workers=min(len(successful_candidates), 4)) as executor:
            futures = [
                executor.submit(
                    self._review_candidates,
                    candidate.model_name,
                    article,
                    portfolio,
                    successful_candidates,
                    matched_symbols,
                )
                for candidate in successful_candidates
            ]
            reviews = [future.result() for future in as_completed(futures)]

        try:
            output = self._finalize(
                article=article,
                portfolio=portfolio,
                candidates=successful_candidates,
                reviews=reviews,
                matched_symbols=matched_symbols,
            )
        except Exception as exc:
            logger.warning("Council judge %s failed, using first successful candidate: %s", self.judge_model_name, exc)
            winner = successful_candidates[0]
            output = LLMOutput(
                localized_title=winner.localized_title,
                summary=winner.summary,
                impact_analysis=winner.impact_analysis,
                raw_text=winner.raw_text,
                model_name=self.effective_model_name,
            )

        output.raw_text = json.dumps(
            {
                "mode": "ollama_council",
                "models": self.model_names,
                "judge_model": self.judge_model_name,
                "final": OllamaLLM._extract_json(output.raw_text),
                "candidates": [
                    {
                        "model_name": candidate.model_name,
                        "localized_title": candidate.localized_title,
                        "summary": candidate.summary,
                        "impact_analysis": candidate.impact_analysis,
                        "raw_text": candidate.raw_text,
                        "error": candidate.error,
                    }
                    for candidate in candidates
                ],
                "reviews": [
                    {
                        "reviewer_model": review.reviewer_model,
                        "raw_text": review.raw_text,
                        "error": review.error,
                    }
                    for review in reviews
                ],
            },
            ensure_ascii=False,
        )
        output.metadata = {
            "mode": "ollama_council",
            "models": self.model_names,
            "judge_model": self.judge_model_name,
        }
        return output
