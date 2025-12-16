"""
Django settings for config project.
"""

from pathlib import Path
import os
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# =========================
# Seguridad / Producción
# =========================
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-unsafe-secret-key")

DEBUG = os.environ.get("DEBUG", "False").lower() == "true"

# Render envía el host real. Ponlo por variable o deja fallback seguro.
# Ejemplo en Render: ALLOWED_HOSTS=inventario-backend-fecp.onrender.com
allowed_hosts_env = os.environ.get("ALLOWED_HOSTS", "")
ALLOWED_HOSTS = [h.strip() for h in allowed_hosts_env.split(",") if h.strip()]

# Si no te configuraron ALLOWED_HOSTS (solo por emergencia), permite el dominio de Render
# (siempre mejor setear la variable en Render)
if not ALLOWED_HOSTS and not DEBUG:
    ALLOWED_HOSTS = [".onrender.com"]

# =========================
# Apps
# =========================
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # terceros
    "rest_framework",
    "corsheaders",

    # propias
    "inventario",
]

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_PAGINATION_CLASS": "inventario.pagination.Default30Pagination",
    "PAGE_SIZE": 30,
}

# =========================
# Middleware
# =========================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # ✅ justo después de SecurityMiddleware
    "corsheaders.middleware.CorsMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

# =========================
# Templates
# =========================
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# =========================
# Database (Neon / Postgres)
# =========================
# En Render define: DATABASE_URL = postgresql://...
DATABASES = {
    "default": dj_database_url.config(
        default=os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
        conn_max_age=0,     # ✅ estable incluso si luego activas pooling
        ssl_require=not DEBUG,
    )
}

# =========================
# Password validation
# =========================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# =========================
# Internacionalización
# =========================
LANGUAGE_CODE = "es-co"
TIME_ZONE = "America/Bogota"
USE_I18N = True
USE_TZ = True

# =========================
# Static files (WhiteNoise)
# =========================
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# =========================
# CORS
# =========================
# ✅ NO dejes CORS_ALLOW_ALL_ORIGINS=True en producción
# En Render define: CORS_ALLOWED_ORIGINS=https://tu-frontend.onrender.com
cors_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "")
CORS_ALLOWED_ORIGINS = [o.strip() for o in cors_origins.split(",") if o.strip()]

# Para desarrollo local
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOW_ALL_ORIGINS = False

# =========================
# Default PK
# =========================
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
