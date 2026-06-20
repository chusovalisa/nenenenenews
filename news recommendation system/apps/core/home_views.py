from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import resolve, reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import FormView
import re
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from apps.core.forms import SignUpForm
from apps.news.models import NewsArticle, NewsSource
from apps.pipeline.models import PipelineJob
from apps.pipeline.services import PipelineOrchestrator
from apps.portfolios.forms import AssetForm, PortfolioForm, PortfolioPositionForm
from apps.portfolios.models import Asset, Portfolio, PortfolioPosition


def _resolve_ui_redirect(request: HttpRequest, fallback: str = "dashboard") -> str:
    candidates = [
        request.POST.get("next", ""),
        request.GET.get("next", ""),
        request.META.get("HTTP_REFERER", ""),
    ]
    fallback_map = {
        "dashboard": "ui-dashboard",
        "home": "ui-home",
    }
    fallback_url = reverse(fallback_map.get(fallback, fallback))
    for candidate in candidates:
        if not candidate:
            continue
        if not url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            if not candidate.startswith("/"):
                continue
        path_candidate = urlsplit(candidate).path or candidate
        try:
            match = resolve(path_candidate)
        except Exception:
            continue
        if match.app_name == "admin" or match.route.startswith("api/"):
            continue
        return path_candidate
    return fallback_url


def _append_query_value(url: str, key: str, value: str | int) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query[key] = str(value)
    new_query = urlencode(query)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))


def _parse_lookback_days(raw_value: str | None, default: int = 1) -> int:
    try:
        return max(1, min(int(raw_value or default), 365))
    except (TypeError, ValueError):
        return default


def home(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("ui-dashboard")
    return render(request, "home.html")


def _dashboard_context(request: HttpRequest, portfolio_form=None, asset_form=None) -> dict:
    return {
        "portfolio_form": portfolio_form or PortfolioForm(user=request.user),
        "asset_form": asset_form or AssetForm(user=request.user),
        "portfolios": Portfolio.objects.filter(user=request.user).prefetch_related("positions__asset"),
        "jobs": PipelineJob.objects.filter(user=request.user).order_by("-created_at")[:10],
        "asset_count": Asset.objects.filter(user=request.user).count(),
        "source_count": NewsSource.objects.filter(is_active=True).count(),
        "article_count": NewsArticle.objects.count(),
    }


def _clean_digest_text(value: str) -> str:
    cleaned = str(value or "")
    for _ in range(2):
        cleaned = unescape(cleaned)
    cleaned = re.sub(r"(?:&amp;)?&?quot;?", '"', cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _focus_impact_text(value: str, matched_symbols: list[str]) -> str:
    cleaned = _clean_digest_text(value)
    symbols = [str(symbol).strip().upper() for symbol in matched_symbols if str(symbol).strip()]
    if not symbols:
        return cleaned
    return re.sub(
        r"(Проверьте экспозиции по активам:\s*)[^.]+",
        rf"\1{', '.join(symbols)}",
        cleaned,
    )


def _prepare_digest_items(raw_items: list[dict]) -> list[dict]:
    prepared = []
    for item in raw_items:
        matched_symbols = item.get("matched_symbols", []) or []
        factchecks = item.get("factcheck", []) or []
        statuses = [check.get("status") for check in factchecks if check.get("status")]
        if statuses and any(status == "confirmed" for status in statuses):
            verification_status = "confirmed"
            verification_label = "Подтверждено"
        elif statuses and any(status in {"not_confirmed", "contradicted"} for status in statuses):
            verification_status = "not_confirmed"
            verification_label = "Не подтверждено"
        else:
            verification_status = "insufficient"
            verification_label = "Недостаточно данных"

        claim_checks = []
        sources = []
        seen_urls = set()
        for check in factchecks:
            claim_status = check.get("status", "insufficient_data")
            evidences = []
            for evidence in check.get("evidence", []) or []:
                label = evidence.get("label", "")
                if claim_status == "confirmed" and label not in {"support", "source_support"}:
                    continue
                if claim_status == "not_confirmed":
                    continue
                if claim_status == "contradicted" and label != "contradict":
                    continue
                if claim_status == "insufficient_data":
                    continue
                url = item.get("url", "")
                if not url:
                    continue
                payload = {
                    "url": url,
                    "excerpt": evidence.get("excerpt", ""),
                    "label": label,
                    "score": evidence.get("score", 0),
                }
                evidences.append(payload)
                if url not in seen_urls:
                    seen_urls.add(url)
                    sources.append(payload)

            evidences = evidences[:1]

            claim_checks.append(
                {
                    "claim": check.get("claim", ""),
                    "status": claim_status,
                    "confidence": check.get("confidence", 0),
                    "evidence": evidences,
                }
            )

        prepared.append(
            {
                "title": _clean_digest_text(item.get("title", "")),
                "url": item.get("url", ""),
                "summary": _clean_digest_text(item.get("summary", "")),
                "impact_analysis": _focus_impact_text(item.get("impact_analysis", ""), matched_symbols),
                "matched_symbols": matched_symbols,
                "portfolio_relevance": item.get("portfolio_relevance", []) or [],
                "verification_status": verification_status,
                "verification_label": verification_label,
                "claim_checks": claim_checks,
                "sources": sources,
            }
        )
    return prepared


def _portfolio_context(request: HttpRequest, portfolio: Portfolio, asset_form=None) -> dict:
    latest_digest = (
        PipelineJob.objects.filter(
            user=request.user,
            portfolio=portfolio,
            job_type=PipelineJob.JobType.DIGEST,
            status=PipelineJob.Status.DONE,
        )
        .order_by("-created_at")
        .first()
    )
    latest_digest_payload = latest_digest.result if latest_digest else None
    return {
        "portfolio": portfolio,
        "asset_form": asset_form or AssetForm(user=request.user),
        "latest_digest": latest_digest_payload,
        "latest_digest_items": _prepare_digest_items(latest_digest_payload.get("items", [])) if latest_digest_payload else [],
        "latest_digest_job": latest_digest,
    }


class AppLoginView(LoginView):
    template_name = "auth/login.html"
    redirect_authenticated_user = True


class AppLogoutView(LogoutView):
    next_page = reverse_lazy("ui-home")


class SignUpView(FormView):
    template_name = "auth/signup.html"
    form_class = SignUpForm
    success_url = reverse_lazy("ui-dashboard")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("ui-dashboard")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        messages.success(self.request, "Аккаунт создан.")
        return super().form_valid(form)


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    return render(request, "dashboard.html", _dashboard_context(request))


@login_required
@require_POST
def create_portfolio(request: HttpRequest) -> HttpResponse:
    form = PortfolioForm(request.POST, user=request.user)
    if form.is_valid():
        portfolio = form.save(commit=False)
        portfolio.user = request.user
        portfolio.save()
        messages.success(request, f"Портфель {portfolio.name} создан.")
        return redirect("ui-portfolio-detail", portfolio_id=portfolio.id)
    messages.error(request, "Не удалось создать портфель.")
    return render(request, "dashboard.html", _dashboard_context(request, portfolio_form=form), status=400)


@login_required
@require_POST
def delete_portfolio(request: HttpRequest, portfolio_id: int) -> HttpResponse:
    portfolio = get_object_or_404(Portfolio, id=portfolio_id, user=request.user)
    name = portfolio.name
    portfolio.delete()
    messages.success(request, f"Портфель {name} удалён.")
    return redirect("ui-dashboard")


@login_required
@require_POST
def create_asset(request: HttpRequest) -> HttpResponse:
    form = AssetForm(request.POST, user=request.user)
    next_url = _resolve_ui_redirect(request, fallback="dashboard")
    portfolio_id = request.POST.get("portfolio_id")
    if form.is_valid():
        symbol = form.cleaned_data["symbol"]
        defaults = {
            "name": form.cleaned_data["name"],
            "asset_type": Asset.AssetType.STOCK,
            "sector": "",
            "exchange": "",
        }
        asset, created = Asset.objects.get_or_create(user=request.user, symbol=symbol, defaults=defaults)
        if not created:
            updated_fields = []
            for field in ("name",):
                incoming = (defaults.get(field) or "").strip()
                if incoming and not getattr(asset, field):
                    setattr(asset, field, incoming)
                    updated_fields.append(field)
            if updated_fields:
                asset.save(update_fields=updated_fields + ["updated_at"])
        if portfolio_id:
            portfolio = get_object_or_404(Portfolio, id=portfolio_id, user=request.user)
            position, position_created = PortfolioPosition.objects.get_or_create(
                portfolio=portfolio,
                asset=asset,
                defaults={"quantity": 1},
            )
            if position_created:
                messages.success(request, f"Актив {asset.symbol} добавлен в портфель.")
            else:
                messages.success(request, f"Актив {asset.symbol} уже есть в этом портфеле.")
            return redirect("ui-portfolio-detail", portfolio_id=portfolio.id)
        if created:
            messages.success(request, f"Актив {asset.symbol} добавлен.")
        else:
            messages.success(request, f"Актив {asset.symbol} уже есть в вашем списке.")
        return redirect(next_url)

    messages.error(request, "Не удалось добавить актив.")
    if portfolio_id:
        portfolio = get_object_or_404(
            Portfolio.objects.prefetch_related("positions__asset"),
            id=portfolio_id,
            user=request.user,
        )
        return render(
            request,
            "portfolio_detail.html",
            _portfolio_context(request, portfolio, asset_form=form),
            status=400,
        )
    return render(request, "dashboard.html", _dashboard_context(request, asset_form=form), status=400)


@login_required
def portfolio_detail(request: HttpRequest, portfolio_id: int) -> HttpResponse:
    portfolio = get_object_or_404(
        Portfolio.objects.prefetch_related("positions__asset"),
        id=portfolio_id,
        user=request.user,
    )
    return render(request, "portfolio_detail.html", _portfolio_context(request, portfolio))


@login_required
@require_POST
def add_position(request: HttpRequest, portfolio_id: int) -> HttpResponse:
    portfolio = get_object_or_404(Portfolio, id=portfolio_id, user=request.user)
    form = PortfolioPositionForm(request.POST, portfolio=portfolio, user=request.user)
    if form.is_valid():
        position = form.save(commit=False)
        position.portfolio = portfolio
        if not position.quantity:
            position.quantity = 1
        position.save()
        messages.success(request, f"Позиция {position.asset.symbol} добавлена.")
        return redirect("ui-portfolio-detail", portfolio_id=portfolio.id)

    messages.error(request, "Не удалось добавить позицию.")
    return render(
        request,
        "portfolio_detail.html",
        _portfolio_context(request, portfolio),
        status=400,
    )


@login_required
@require_POST
def update_position(request: HttpRequest, portfolio_id: int, position_id: int) -> HttpResponse:
    portfolio = get_object_or_404(Portfolio, id=portfolio_id, user=request.user)
    position = get_object_or_404(PortfolioPosition, id=position_id, portfolio=portfolio)
    form = PortfolioPositionForm(request.POST, instance=position, portfolio=portfolio, user=request.user)
    if form.is_valid():
        form.save()
        messages.success(request, f"Позиция {position.asset.symbol} обновлена.")
        return redirect("ui-portfolio-detail", portfolio_id=portfolio.id)

    messages.error(request, "Не удалось обновить позицию.")
    return render(
        request,
        "portfolio_detail.html",
        _portfolio_context(request, portfolio),
        status=400,
    )


@login_required
@require_POST
def delete_position(request: HttpRequest, portfolio_id: int, position_id: int) -> HttpResponse:
    portfolio = get_object_or_404(Portfolio, id=portfolio_id, user=request.user)
    position = get_object_or_404(PortfolioPosition, id=position_id, portfolio=portfolio)
    symbol = position.asset.symbol
    position.delete()
    messages.success(request, f"Позиция {symbol} удалена.")
    return redirect("ui-portfolio-detail", portfolio_id=portfolio.id)


@login_required
@require_POST
def ingest_news(request: HttpRequest) -> HttpResponse:
    lookback_days = _parse_lookback_days(request.POST.get("lookback_days"))
    try:
        result = PipelineOrchestrator().ingest_news(lookback_days=lookback_days)
    except Exception as exc:
        messages.error(request, f"Ingest завершился ошибкой: {exc}")
        return redirect("ui-dashboard")
    messages.success(
        request,
        f"Новости обновлены. Источников: {result.get('sources', 0)}, новых статей: {result.get('created_articles', 0)}.",
    )
    return redirect("ui-dashboard")


@login_required
@require_POST
def build_digest(request: HttpRequest, portfolio_id: int) -> HttpResponse:
    portfolio = get_object_or_404(Portfolio, id=portfolio_id, user=request.user)
    top_k_raw = request.POST.get("top_k", "5")
    lookback_days = _parse_lookback_days(request.POST.get("lookback_days"))
    try:
        top_k = max(1, min(int(top_k_raw), 20))
    except ValueError:
        top_k = 5
    try:
        payload = PipelineOrchestrator().build_digest(
            user_id=request.user.id,
            portfolio_id=portfolio.id,
            top_k=top_k,
            lookback_days=lookback_days,
        )
    except Exception as exc:
        messages.error(request, f"Не удалось построить дайджест: {exc}")
        return redirect("ui-portfolio-detail", portfolio_id=portfolio.id)
    item_count = len(payload.get("items", []))
    if item_count == 0:
        refresh = payload.get("news_refresh") or {}
        lookback_days = refresh.get("lookback_days", 1)
        messages.warning(
            request,
            f"Новости обновлены, но за последние {lookback_days} дн. релевантных новостей по портфелю не найдено.",
        )
    else:
        messages.success(request, f"Дайджест построен. Новостей в выдаче: {item_count}.")
    return redirect("ui-portfolio-detail", portfolio_id=portfolio.id)
