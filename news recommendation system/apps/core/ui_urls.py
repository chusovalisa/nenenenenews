from django.urls import path

from apps.core.home_views import (
    AppLoginView,
    AppLogoutView,
    SignUpView,
    add_position,
    build_digest,
    create_asset,
    create_portfolio,
    dashboard,
    delete_portfolio,
    delete_position,
    home,
    ingest_news,
    portfolio_detail,
    update_position,
)


urlpatterns = [
    path("", home, name="ui-home"),
    path("login/", AppLoginView.as_view(), name="ui-login"),
    path("logout/", AppLogoutView.as_view(), name="ui-logout"),
    path("signup/", SignUpView.as_view(), name="ui-signup"),
    path("dashboard/", dashboard, name="ui-dashboard"),
    path("assets/create/", create_asset, name="ui-asset-create"),
    path("portfolios/create/", create_portfolio, name="ui-portfolio-create"),
    path("portfolios/<int:portfolio_id>/delete/", delete_portfolio, name="ui-portfolio-delete"),
    path("portfolios/<int:portfolio_id>/", portfolio_detail, name="ui-portfolio-detail"),
    path("portfolios/<int:portfolio_id>/positions/add/", add_position, name="ui-position-add"),
    path("portfolios/<int:portfolio_id>/positions/<int:position_id>/update/", update_position, name="ui-position-update"),
    path("portfolios/<int:portfolio_id>/positions/<int:position_id>/delete/", delete_position, name="ui-position-delete"),
    path("portfolios/<int:portfolio_id>/digest/", build_digest, name="ui-build-digest"),
    path("news/ingest/", ingest_news, name="ui-ingest-news"),
]
