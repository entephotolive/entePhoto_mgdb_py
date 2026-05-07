import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / ".env.local", override=True)
load_dotenv(BASE_DIR / ".env.production", override=False)


def get_env(name, default=None, required=False):
    value = os.getenv(name, default)
    if required and not value:
        raise ImproperlyConfigured(f"Missing required environment variable: {name}")
    return value


def get_env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer") from exc


SECRET_KEY = get_env(
    "SECRET_KEY",
    "django-insecure-fallback-dev-key-change-in-production",
)
DEBUG = get_env_bool("DEBUG", False)
ALLOWED_HOSTS = [host.strip() for host in get_env("ALLOWED_HOSTS", "*").split(",") if host.strip()]
MONGODB_URI = get_env("MONGODB_URI", required=True)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "channels",
    "recognition",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",

    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",

    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",

    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",

    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
# CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

# Explicitly list allowed WebSocket origins for the Channels AllowedHostsOriginValidator.
# In production replace with your real domain.
# CORS_ALLOWED_ORIGINS = [
#     "http://localhost:3000",
#     "http://127.0.0.1:3000",
#     "http://localhost:8000",
#     "http://127.0.0.1:8000",
# ]
CORS_ALLOW_ALL_ORIGINS = False

CORS_ALLOWED_ORIGINS = [
    "https://entephoto.co.in",
    "https://www.entephoto.co.in",
]
CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]

CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "x-admin-token",
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "upload": get_env("UPLOAD_RATE", "30/min"),
        "scan": get_env("SCAN_RATE", "30/min"),
        "read": get_env("READ_RATE", "120/min"),
        "health": get_env("HEALTH_RATE", "120/min"),
    },
    "UNAUTHENTICATED_USER": None,
    "UNAUTHENTICATED_TOKEN": None,
}

ROOT_URLCONF = "config.urls"

ASGI_APPLICATION = "config.asgi.application"

# In-memory channel layer — zero infra, single-process only.
# Swap to channels_redis.core.RedisChannelLayer for multi-process / production.
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",

                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"  # Kept for tooling only; server runs via ASGI.

# The app now uses MongoDB Atlas through PyMongo only.
# Keeping Django's dummy backend here makes any accidental ORM access fail fast.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.dummy",
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = get_env("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

MAX_UPLOAD_MB = get_env_int("MAX_UPLOAD_MB", 10)
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = get_env_int("DATA_UPLOAD_MAX_MEMORY_SIZE", MAX_UPLOAD_BYTES)
FILE_UPLOAD_MAX_MEMORY_SIZE = get_env_int("FILE_UPLOAD_MAX_MEMORY_SIZE", MAX_UPLOAD_BYTES)

ALLOWED_IMAGE_MIME_TYPES = {
    t.strip().lower()
    for t in get_env("ALLOWED_IMAGE_MIME_TYPES", "image/jpeg,image/png,image/webp").split(",")
    if t.strip()
}

# Face matching tuning.
FACE_MATCH_TOLERANCE = float(get_env("FACE_MATCH_TOLERANCE", "0.5"))
MAX_MATCHED_PHOTOS = get_env_int("MAX_MATCHED_PHOTOS", 200)

# Attendee session cookie.
SESSION_COOKIE_NAME = get_env("SESSION_COOKIE_NAME", "pc_session")
SESSION_TTL_SECONDS = get_env_int("SESSION_TTL_SECONDS", 60 * 60 * 24 * 7)  # 7 days
# For cross-site cookies (e.g. frontend on a different domain), Samesite=None is required.
# Note: SameSite=None requires SECURE=True, which requires HTTPS.
SESSION_COOKIE_SAMESITE = get_env("SESSION_COOKIE_SAMESITE", "Lax" if DEBUG else "None")
SESSION_COOKIE_SECURE = get_env_bool("SESSION_COOKIE_SECURE", not DEBUG)
SESSION_COOKIE_HTTPONLY = True

# Celery is optional; the API falls back to synchronous processing when broker is not configured.
CELERY_BROKER_URL = get_env("CELERY_BROKER_URL", "")
CELERY_RESULT_BACKEND = get_env("CELERY_RESULT_BACKEND", "")
USE_ASYNC_FACE_PROCESSING = get_env_bool("USE_ASYNC_FACE_PROCESSING", bool(CELERY_BROKER_URL))

# Optional admin protection for destructive endpoints (e.g., photo delete).
ADMIN_TOKEN = get_env("ADMIN_TOKEN", "")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = False

SESSION_COOKIE_DOMAIN = ".entephoto.co.in"
