"""
Production settings for the Ubuntu + Nginx + Gunicorn + PostgreSQL deployment.

Usage on the server:

    DJANGO_SETTINGS_MODULE=config.production_settings

This module imports the base settings from ``config.settings`` and then
enforces production-only values on top of them. ``config.settings`` stays the
local development settings and ``config.test_settings`` stays unchanged.

Every required value comes from environment variables. Validation errors
raise ``ImproperlyConfigured`` and name the variable only, never its value.
"""

import ipaddress
import os
import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured


# =========================================================
# Shared validation helpers
# =========================================================

HOSTNAME_LABEL_PATTERN = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
NON_NEGATIVE_INTEGER_PATTERN = re.compile(r"^\d+$")
LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain"}
DB_SSLMODE_VALUES = {
    "disable",
    "allow",
    "prefer",
    "require",
    "verify-ca",
    "verify-full",
}
MIN_SECRET_KEY_LENGTH = 50
MIN_JWT_SIGNING_KEY_LENGTH = 32
HSTS_PRELOAD_MIN_SECONDS = 31536000


def read_integer_setting(name, *, default, minimum, maximum=None):
    """Read an integer from the environment without echoing invalid values.

    ``default=None`` makes the variable required. It reads ``os.environ``
    directly so it also works when the base settings failed mid-import
    (after ``.env`` was already loaded).
    """
    raw_value = os.environ.get(
        name,
        "" if default is None else str(default),
    ).strip()

    if not raw_value and default is None:
        raise ImproperlyConfigured(f"{name} is required in production.")

    if not NON_NEGATIVE_INTEGER_PATTERN.match(raw_value):
        raise ImproperlyConfigured(f"{name} must be a whole number.")

    value = int(raw_value)
    if value < minimum or (maximum is not None and value > maximum):
        allowed_range = (
            f"between {minimum} and {maximum}"
            if maximum is not None
            else f"at least {minimum}"
        )
        raise ImproperlyConfigured(f"{name} must be {allowed_range}.")

    return value


def validate_integer_settings():
    """Validate integers that the base settings cast with ``env.int``."""
    return {
        "DB_PORT": read_integer_setting(
            "DB_PORT",
            default=None,
            minimum=1,
            maximum=65535,
        ),
        "SECURE_HSTS_SECONDS": read_integer_setting(
            "SECURE_HSTS_SECONDS",
            default=0,
            minimum=0,
        ),
    }


def is_local_hostname(hostname):
    if hostname in LOCAL_HOSTNAMES or hostname.endswith(".localhost"):
        return True

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False

    return address.is_loopback or address.is_unspecified


def is_valid_hostname(hostname):
    if not hostname or len(hostname) > 253:
        return False

    return all(
        HOSTNAME_LABEL_PATTERN.match(label) for label in hostname.split(".")
    )


def is_vercel_hostname(hostname):
    return hostname == "vercel.app" or hostname.endswith(".vercel.app")


def require_setting(name):
    """Return a required, non-empty environment value."""
    value = env.str(name, default="").strip()

    if not value:
        raise ImproperlyConfigured(f"{name} is required in production.")

    return value


def read_production_hosts(name):
    """Read ALLOWED_HOSTS as plain hostnames only."""
    hosts = []

    for raw_host in env.list(name, default=[]):
        host = raw_host.strip().lower()

        if not host:
            raise ImproperlyConfigured(f"{name} cannot contain empty entries.")

        if "*" in host:
            raise ImproperlyConfigured(f"{name} cannot contain wildcards.")

        if any(character in host for character in ":/?#@"):
            raise ImproperlyConfigured(
                f"Invalid host '{host}' in {name}. "
                "Use hostnames only, without scheme, port, path or query."
            )

        if not is_valid_hostname(host):
            raise ImproperlyConfigured(f"Invalid host '{host}' in {name}.")

        if is_local_hostname(host):
            raise ImproperlyConfigured(
                f"{name} cannot contain local hosts in production."
            )

        if host not in hosts:
            hosts.append(host)

    if not hosts:
        raise ImproperlyConfigured(f"{name} is required in production.")

    return hosts


def read_production_origins(name):
    """Read exact HTTPS origins and reject development or wildcard values."""
    raw_origins = env.list(name, default=[])
    if not any(origin.strip() for origin in raw_origins):
        raise ImproperlyConfigured(f"{name} is required in production.")

    # يعيد استخدام تحقق الإعدادات الأساسية (wildcard وpath وquery وfragment).
    base_origins = normalize_origins(raw_origins, setting_name=name)

    origins = []
    for origin in base_origins:
        if "*" in origin:
            raise ImproperlyConfigured(f"{name} cannot contain wildcards.")

        parsed_origin = urlsplit(origin)
        if parsed_origin.scheme != "https":
            raise ImproperlyConfigured(
                f"Invalid origin '{origin}' in {name}. "
                "Production origins must use https://."
            )

        try:
            port = parsed_origin.port
        except ValueError:
            raise ImproperlyConfigured(
                f"Invalid origin '{origin}' in {name}."
            ) from None

        hostname = (parsed_origin.hostname or "").lower()
        if (
            parsed_origin.username is not None
            or parsed_origin.password is not None
            or not is_valid_hostname(hostname)
        ):
            raise ImproperlyConfigured(f"Invalid origin '{origin}' in {name}.")

        if is_local_hostname(hostname):
            raise ImproperlyConfigured(
                f"{name} cannot contain local origins in production."
            )

        if is_vercel_hostname(hostname):
            raise ImproperlyConfigured(
                f"{name} cannot contain vercel.app origins in production. "
                "Use the custom frontend domain."
            )

        normalized_origin = f"https://{hostname}" + (f":{port}" if port else "")
        if normalized_origin not in origins:
            origins.append(normalized_origin)

    return origins


def read_cookie_domain(name):
    """Return None for host-only cookies, or a validated explicit domain."""
    domain = env.str(name, default="").strip().lower()
    if not domain:
        return None

    hostname = domain[1:] if domain.startswith(".") else domain

    if not is_valid_hostname(hostname) or is_local_hostname(hostname):
        raise ImproperlyConfigured(
            f"{name} must be a plain domain name without scheme, port or path."
        )

    return domain


def reject_disabled_secure_cookie(name):
    """Production cookies are always Secure; an explicit False is a mistake."""
    if not env.bool(name, default=True):
        raise ImproperlyConfigured(f"{name} cannot be disabled in production.")


def read_media_root(name):
    value = require_setting(name)
    path = PurePosixPath(value)

    if not path.is_absolute():
        raise ImproperlyConfigured(f"{name} must be an absolute path.")

    if ".." in path.parts or path == PurePosixPath("/"):
        raise ImproperlyConfigured(
            f"{name} must be a dedicated absolute directory."
        )

    return str(path)


# =========================================================
# Base settings
# =========================================================

_base_settings_failed = False
try:
    from config.settings import *  # noqa: E402,F401,F403
except ValueError:
    _base_settings_failed = True

if _base_settings_failed:
    # الإعدادات الأساسية تستخدم env.int وقد تفشل بـValueError يحتوي القيمة.
    # نعيد التحقق خارج except حتى لا يُربط الخطأ الأصلي بالـtraceback،
    # ونرفع ImproperlyConfigured باسم المتغير فقط.
    validate_integer_settings()
    raise ImproperlyConfigured(
        "A numeric environment variable has an invalid value."
    )

from config.settings import (  # noqa: E402
    DATABASES,
    env,
    normalize_origins,
    read_samesite_setting,
)


# =========================================================
# Core
# =========================================================

if env.bool("DEBUG", default=False):
    raise ImproperlyConfigured(
        "DEBUG cannot be enabled in production. Remove DEBUG or set it to False."
    )

DEBUG = False

_integer_settings = validate_integer_settings()

SECRET_KEY = require_setting("SECRET_KEY")
if (
    SECRET_KEY.startswith("django-insecure-")
    or len(SECRET_KEY) < MIN_SECRET_KEY_LENGTH
):
    raise ImproperlyConfigured(
        f"SECRET_KEY must be a random value of at least "
        f"{MIN_SECRET_KEY_LENGTH} characters."
    )

_jwt_signing_key = require_setting("JWT_SIGNING_KEY")
if len(_jwt_signing_key) < MIN_JWT_SIGNING_KEY_LENGTH:
    raise ImproperlyConfigured(
        f"JWT_SIGNING_KEY must be a random value of at least "
        f"{MIN_JWT_SIGNING_KEY_LENGTH} characters."
    )
if _jwt_signing_key == SECRET_KEY:
    raise ImproperlyConfigured("JWT_SIGNING_KEY must differ from SECRET_KEY.")

SIMPLE_JWT = {
    **SIMPLE_JWT,  # noqa: F405
    "SIGNING_KEY": _jwt_signing_key,
}

ALLOWED_HOSTS = read_production_hosts("ALLOWED_HOSTS")


# =========================================================
# Shared cache and client IP handling
# =========================================================

REDIS_URL = require_setting("REDIS_URL")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "TIMEOUT": 300,
        "KEY_PREFIX": "asas",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    },
}

# Keep every inherited DRF setting and trust exactly the single Nginx proxy.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "NUM_PROXIES": 1,
}


# =========================================================
# Frontend, CORS and CSRF origins
# =========================================================

FRONTEND_ORIGINS = read_production_origins("FRONTEND_ORIGINS")
BACKEND_ORIGINS = read_production_origins("BACKEND_ORIGINS")

CORS_ALLOWED_ORIGINS = FRONTEND_ORIGINS

# يلغي Regex نطاقات Vercel الموروث من الإعدادات الأساسية.
CORS_ALLOWED_ORIGIN_REGEXES = []
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = True

# بلا "https://*.vercel.app" الموروثة من الإعدادات الأساسية.
CSRF_TRUSTED_ORIGINS = list(dict.fromkeys([*FRONTEND_ORIGINS, *BACKEND_ORIGINS]))


# =========================================================
# HTTPS behind Nginx
# =========================================================

# Nginx يجب أن يضبط X-Forwarded-Proto بنفسه ولا يمرر قيمة العميل.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

# تبقى 0 حتى يتم التحقق من SSL على الدومين النهائي.
SECURE_HSTS_SECONDS = _integer_settings["SECURE_HSTS_SECONDS"]
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    default=False,
)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)

if SECURE_HSTS_PRELOAD and (
    not SECURE_HSTS_INCLUDE_SUBDOMAINS
    or SECURE_HSTS_SECONDS < HSTS_PRELOAD_MIN_SECONDS
):
    raise ImproperlyConfigured(
        "SECURE_HSTS_PRELOAD requires SECURE_HSTS_INCLUDE_SUBDOMAINS=True "
        f"and SECURE_HSTS_SECONDS >= {HSTS_PRELOAD_MIN_SECONDS}."
    )


# =========================================================
# Cookies
# =========================================================

# أسماء ومسارات Cookies تبقى كما في الإعدادات الأساسية.
# Secure مفروضة دائمًا، لذلك SameSite=None لا يمكن أن تُستخدم مع Cookie غير آمنة،
# ونرفض أي محاولة صريحة لتعطيل Secure.
reject_disabled_secure_cookie("JWT_COOKIE_SECURE")
reject_disabled_secure_cookie("CSRF_COOKIE_SECURE")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
JWT_COOKIE_SECURE = True

JWT_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_HTTPONLY = True

# Frontend وBackend تحت Root Domain واحد (app.example.com وapi.example.com)،
# لذلك Lax هي القيمة الافتراضية في Production.
JWT_COOKIE_SAMESITE = read_samesite_setting(
    "JWT_COOKIE_SAMESITE",
    default="Lax",
)
CSRF_COOKIE_SAMESITE = read_samesite_setting(
    "CSRF_COOKIE_SAMESITE",
    default="Lax",
)

# Host-only للـBackend ما لم يُمرر Domain صريح وصالح.
JWT_COOKIE_DOMAIN = read_cookie_domain("JWT_COOKIE_DOMAIN")


# =========================================================
# Static files
# =========================================================

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}


# =========================================================
# Media files
# =========================================================

# Nginx يخدم الملفات من MEDIA_ROOT؛ Django لا يضيف route لها.
# إنشاء المجلد وصلاحياته مسؤولية DevOps.
MEDIA_ROOT = read_media_root("MEDIA_ROOT")
MEDIA_URL = "/media/"


# =========================================================
# Database
# =========================================================

_db_sslmode = require_setting("DB_SSLMODE").lower()
if _db_sslmode not in DB_SSLMODE_VALUES:
    raise ImproperlyConfigured(
        "DB_SSLMODE must be one of: "
        + ", ".join(sorted(DB_SSLMODE_VALUES))
        + "."
    )

DATABASES = {
    **DATABASES,
    "default": {
        **DATABASES["default"],
        "ENGINE": "django.db.backends.postgresql",
        "NAME": require_setting("DB_NAME"),
        "USER": require_setting("DB_USER"),
        "PASSWORD": require_setting("DB_PASSWORD"),
        "HOST": require_setting("DB_HOST"),
        "PORT": _integer_settings["DB_PORT"],
        "OPTIONS": {
            **DATABASES["default"].get("OPTIONS", {}),
            "sslmode": _db_sslmode,
        },
    },
}


# =========================================================
# Firebase
# =========================================================

# منطق Firebase نفسه لا يتغير؛ نتحقق فقط من وجود الإعدادات عند التفعيل.
if FIREBASE_PUSH_ENABLED:  # noqa: F405
    if not FIREBASE_PROJECT_ID:  # noqa: F405
        raise ImproperlyConfigured(
            "FIREBASE_PROJECT_ID is required when FIREBASE_PUSH_ENABLED=True."
        )

    if not env.str("GOOGLE_APPLICATION_CREDENTIALS", default="").strip():
        raise ImproperlyConfigured(
            "GOOGLE_APPLICATION_CREDENTIALS is required when "
            "FIREBASE_PUSH_ENABLED=True."
        )
