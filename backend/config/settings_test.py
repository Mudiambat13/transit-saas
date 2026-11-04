import os

os.environ.setdefault("DJANGO_DEBUG", "1")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key")
os.environ.pop("POSTGRES_DB", None)

from .settings import *  # noqa: E402,F401,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_CLASSES": [],
}
# Base fichier (et non :memory:) : les tests de concurrence utilisent plusieurs threads ;
# `timeout` fait attendre SQLite au lieu de lever « database is locked ».
import tempfile

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(tempfile.gettempdir(), "transit_test.sqlite3"),
        "OPTIONS": {"timeout": 30, "transaction_mode": "IMMEDIATE"},  # les écrivains font la queue au lieu de se bloquer
        "TEST": {"NAME": os.path.join(tempfile.gettempdir(), f"transit_test_{os.getpid()}.sqlite3")},
    }
}

# `TEST_DB=postgres pytest` : rejoue toute la suite sur PostgreSQL (variables POSTGRES_* ou valeurs ci-dessous).
if os.environ.get("TEST_DB") == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "transit"),
            "USER": os.environ.get("POSTGRES_USER", "transit"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "transit"),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
