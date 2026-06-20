from django.shortcuts import redirect
from django.urls import resolve, reverse


class ApiBrowserRedirectMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._should_redirect(request):
            destination = reverse("ui-dashboard") if request.user.is_authenticated else reverse("ui-home")
            return redirect(destination)
        return self.get_response(request)

    @staticmethod
    def _should_redirect(request) -> bool:
        if not request.path.startswith("/api/"):
            return False
        if request.method not in {"GET", "HEAD"}:
            return False
        accepts = request.headers.get("Accept", "")
        if "text/html" not in accepts:
            return False
        try:
            match = resolve(request.path)
        except Exception:
            return False
        return bool(match)
