import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-not-secret")
DEBUG = os.environ.get("DEBUG", "1") == "1"
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "*").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [x.strip() for x in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if x.strip()]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "apprentice",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
}]
WSGI_APPLICATION = "config.wsgi.application"

# Postgres (e.g. Supabase) when DATABASE_URL is set; SQLite for local development.
if os.environ.get("DATABASE_URL"):
    DATABASES = {"default": dj_database_url.parse(os.environ["DATABASE_URL"], conn_max_age=60, conn_health_checks=True)}
    # Supabase's transaction pooler (port 6543) does not support server-side cursors.
    DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
else:
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("SQLITE_PATH", BASE_DIR / "db.sqlite3"),
        # Background coverage threads write while requests run; wait instead of "database is locked".
        "OPTIONS": {"timeout": 20},
    }}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

USE_TZ = True
TIME_ZONE = "UTC"
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DATA_UPLOAD_MAX_MEMORY_SIZE = 8 * 1024 * 1024
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
INTERVIEWER_AGENT_ID = os.environ.get("INTERVIEWER_AGENT_ID", "")
TUTOR_AGENT_ID = os.environ.get("TUTOR_AGENT_ID", "")
AGENT_LLM = os.environ.get("AGENT_LLM", "claude-sonnet-5")

AZURE_VISION_ENDPOINT = os.environ.get("AZURE_VISION_ENDPOINT", "")
AZURE_VISION_DEPLOYMENT = os.environ.get("AZURE_VISION_DEPLOYMENT", "")
AZURE_VISION_API_KEY = os.environ.get("AZURE_VISION_API_KEY", "")
