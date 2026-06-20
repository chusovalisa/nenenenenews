from pathlib import Path
import json
import os

BASE_DIR = Path(__file__).resolve().parent.parent


def load_env_file(path: Path) -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(path)
        return
    except ImportError:
        pass
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_env_file(BASE_DIR / ".env")


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_json(name: str, default):
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


SECRET_KEY = env("DJANGO_SECRET_KEY", "change-me-in-env")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "*").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.core",
    "apps.portfolios",
    "apps.news",
    "apps.recommendations",
    "apps.llm",
    "apps.factcheck",
    "apps.pipeline",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.ApiBrowserRedirectMiddleware",
]

ROOT_URLCONF = "DjangoProject.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "DjangoProject.wsgi.application"
ASGI_APPLICATION = "DjangoProject.asgi.application"

DB_ENGINE = env("DB_ENGINE", "sqlite")
if DB_ENGINE == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB", "finance_news"),
            "USER": env("POSTGRES_USER", "postgres"),
            "PASSWORD": env("POSTGRES_PASSWORD", "postgres"),
            "HOST": env("POSTGRES_HOST", "localhost"),
            "PORT": env("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = env("TIME_ZONE", "Europe/Moscow")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

NEWS_SOURCES = env_json("NEWS_SOURCES", [])

SCORING_WEIGHTS = env_json(
    "SCORING_WEIGHTS",
    {
        "asset_overlap": 0.6,
        "source_reliability": 0.25,
        "freshness": 0.15,
    },
)

NEWS_LOOKBACK_DAYS = int(env("NEWS_LOOKBACK_DAYS", "1"))
EMBEDDING_MODEL_ID = env("EMBEDDING_MODEL_ID", "sentence-transformers/all-MiniLM-L6-v2")
EMBEDDING_BATCH_SIZE = int(env("EMBEDDING_BATCH_SIZE", "32"))
EMBEDDING_FALLBACK_DIM = int(env("EMBEDDING_FALLBACK_DIM", "384"))
EMBEDDING_LOCAL_FILES_ONLY = env_bool("EMBEDDING_LOCAL_FILES_ONLY", True)
VECTOR_COLLECTION = env("VECTOR_COLLECTION", "news_chunks")
QDRANT_URL = env("QDRANT_URL", "")
QDRANT_API_KEY = env("QDRANT_API_KEY", "")
QDRANT_PATH = env("QDRANT_PATH", str(BASE_DIR / "qdrant_data"))
PROMPT_VERSION = env("PROMPT_VERSION", "v6-ru-title-strict")
OLLAMA_BASE_URL = env("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = env("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_COUNCIL_MODELS = env_json("OLLAMA_COUNCIL_MODELS", [])
OLLAMA_COUNCIL_JUDGE_MODEL = env("OLLAMA_COUNCIL_JUDGE_MODEL", "")
OLLAMA_FALLBACK_MODEL = env("OLLAMA_FALLBACK_MODEL", "")
OLLAMA_TIMEOUT_SECONDS = int(env("OLLAMA_TIMEOUT_SECONDS", "120"))

NEWSAPI_KEY = env("NEWSAPI_KEY", "")
FINNHUB_API_KEY = env("FINNHUB_API_KEY", "")
ALPHA_VANTAGE_API_KEY = env("ALPHA_VANTAGE_API_KEY", "")
MARKETAUX_API_KEY = env("MARKETAUX_API_KEY", "")
GNEWS_API_KEY = env("GNEWS_API_KEY", "")
NEWS_API_TIMEOUT_SECONDS = int(env("NEWS_API_TIMEOUT_SECONDS", "15"))
