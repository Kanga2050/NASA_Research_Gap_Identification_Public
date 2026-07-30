from pathlib import Path
import os

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parents[3]

# Secure-by-default: DEBUG must be explicitly opted into, never assumed.
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"


def _dev_only_persistent_secret(env_var: str, file_name: str) -> str:
    """Return a secret suitable for local dev only: read from env, else read/create
    a local file so the value is stable across restarts. Raises outside DEBUG."""
    value = os.environ.get(env_var, "")
    if value:
        return value
    if not DEBUG:
        raise ImproperlyConfigured(f"{env_var} must be set when DJANGO_DEBUG is not enabled.")
    key_file = BASE_DIR / file_name
    if key_file.exists():
        return key_file.read_text().strip()
    from django.core.management.utils import get_random_secret_key

    value = get_random_secret_key()
    key_file.write_text(value)
    return value


SECRET_KEY = _dev_only_persistent_secret("DJANGO_SECRET_KEY", ".dev_secret_key")
ALLOWED_HOSTS = [host for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",") if host]

# Fernet key for encrypting third-party API keys at rest (AgentSettings.gemini_api_key,
# ExternalApiSettings.openalex_api_key). See App/Frontend/portal/crypto_fields.py.
if os.environ.get("DJANGO_FIELD_ENCRYPTION_KEY"):
    FIELD_ENCRYPTION_KEY = os.environ["DJANGO_FIELD_ENCRYPTION_KEY"]
elif DEBUG:
    from cryptography.fernet import Fernet

    _key_file = BASE_DIR / ".dev_field_encryption_key"
    if _key_file.exists():
        FIELD_ENCRYPTION_KEY = _key_file.read_text().strip()
    else:
        FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
        _key_file.write_text(FIELD_ENCRYPTION_KEY)
else:
    FIELD_ENCRYPTION_KEY = ""  # EncryptedCharField raises ImproperlyConfigured on first use

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "App.Frontend.portal.apps.PortalConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "App.Frontend.webapp.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "App" / "Frontend" / "templates"],
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

WSGI_APPLICATION = "App.Frontend.webapp.wsgi.application"
ASGI_APPLICATION = "App.Frontend.webapp.asgi.application"

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

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
# No LOGOUT_REDIRECT_URL: LogoutView renders registration/logged_out.html
# (a confirmation page) instead of redirecting straight back to login.

DATA_ROOT = BASE_DIR / "App" / "UserData"
CSV_ROOT = DATA_ROOT / "csvs"
HTML_ROOT = DATA_ROOT / "html"
TASK_ROOT = DATA_ROOT / "tasks"

# Allow uploading a whole PDF collection at once (Django defaults to 100 files per
# request); large individual PDFs already stream to a temp file past 2.5 MB.
DATA_UPLOAD_MAX_NUMBER_FILES = 1000