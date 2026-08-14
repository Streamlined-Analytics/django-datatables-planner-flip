"""Minimal settings for the paginator-clamp -> planner-flip reproduction.

Everything here is the smallest configuration that exercises the stock
django-rest-framework-datatables request path. ``DEBUG = True`` is load-bearing:
it enables ``django.db.backends`` query logging so the clamped ``LIMIT`` and the
query duration appear in the web container's log.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "insecure-key-for-local-repro-only")
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.postgres",
    "rest_framework",
    "rest_framework_datatables",
    "people",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "repro"),
        "USER": os.environ.get("POSTGRES_USER", "repro"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "repro"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        # Matches the production system where the bug was observed. Server-side
        # prepared statements were investigated and ruled out as the cause.
        "OPTIONS": {"prepare_threshold": None},
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
        "rest_framework_datatables.renderers.DatatablesRenderer",
    ),
    "DEFAULT_FILTER_BACKENDS": (
        "rest_framework_datatables.filters.DatatablesFilterBackend",
    ),
    "DEFAULT_PAGINATION_CLASS": "people.pagination.LoggingDatatablesPagination",
    "PAGE_SIZE": 25,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "loggers": {
        "django.db.backends": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "people": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
