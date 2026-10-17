import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase


BASE_DIR = Path(__file__).resolve().parent.parent

# كل متغيرات البيئة التي تقرأها الإعدادات؛ تُزال من بيئة الـsubprocess
# حتى لا تتسرب قيم جهاز المطور إلى الاختبار.
MANAGED_ENVIRONMENT_VARIABLES = {
    "DJANGO_SETTINGS_MODULE",
    "SECRET_KEY",
    "DEBUG",
    "LOG_LEVEL",
    "ALLOWED_HOSTS",
    "SECURE_SSL_REDIRECT",
    "SECURE_HSTS_SECONDS",
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    "SECURE_HSTS_PRELOAD",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "DB_HOST",
    "DB_PORT",
    "DB_SSLMODE",
    "MOBILE_MAX_ACTIVE_DEVICES_PER_GUARDIAN",
    "FIREBASE_PUSH_ENABLED",
    "FIREBASE_PROJECT_ID",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "FIREBASE_HTTP_TIMEOUT_SECONDS",
    "PUSH_SEND_CHUNK_SIZE",
    "PUSH_MAX_ATTEMPTS",
    "PUSH_MAX_AGE_HOURS",
    "PUSH_WORKER_BATCH_SIZE",
    "PUSH_LEASE_SECONDS",
    "PUSH_WORKER_POLL_SECONDS",
    "ANNOUNCEMENT_NOTIFY_HOUR",
    "JWT_SIGNING_KEY",
    "JWT_ACCESS_COOKIE_NAME",
    "JWT_REFRESH_COOKIE_NAME",
    "JWT_COOKIE_SECURE",
    "JWT_COOKIE_SAMESITE",
    "JWT_COOKIE_DOMAIN",
    "FRONTEND_ORIGINS",
    "BACKEND_ORIGINS",
    "CSRF_COOKIE_SECURE",
    "CSRF_COOKIE_SAMESITE",
    "MEDIA_ROOT",
    "MEDIA_URL",
    "ADMIN_URL_PATH",
}

# قيم اختبارية وهمية فقط.
TEST_SECRET_KEY = "test-only-secret-key-" + "s" * 50
TEST_JWT_SIGNING_KEY = "test-only-jwt-signing-key-" + "j" * 40
TEST_DB_PASSWORD = "test-only-db-password-sentinel"

VALID_PRODUCTION_ENVIRONMENT = {
    "SECRET_KEY": TEST_SECRET_KEY,
    "JWT_SIGNING_KEY": TEST_JWT_SIGNING_KEY,
    "ALLOWED_HOSTS": "api.example.com",
    "FRONTEND_ORIGINS": "https://app.example.com",
    "BACKEND_ORIGINS": "https://api.example.com",
    "DB_NAME": "asas_test",
    "DB_USER": "asas_test_user",
    "DB_PASSWORD": TEST_DB_PASSWORD,
    "DB_HOST": "127.0.0.1",
    "DB_PORT": "5432",
    "DB_SSLMODE": "disable",
    "MEDIA_ROOT": "/srv/test-media",
    "ADMIN_URL_PATH": "manage-x7k2/",
}

DEVELOPMENT_ENVIRONMENT = {
    "SECRET_KEY": "test-only-development-secret",
    "JWT_SIGNING_KEY": "test-only-development-jwt-key",
    "DEBUG": "True",
    "DB_NAME": "asas_test",
    "DB_USER": "asas_test_user",
    "DB_PASSWORD": TEST_DB_PASSWORD,
}

PUSH_WORKER_DEFAULTS = {
    "FIREBASE_HTTP_TIMEOUT_SECONDS": 10,
    "PUSH_SEND_CHUNK_SIZE": 50,
    "PUSH_MAX_ATTEMPTS": 6,
    "PUSH_MAX_AGE_HOURS": 24,
    "PUSH_WORKER_BATCH_SIZE": 50,
    "PUSH_LEASE_SECONDS": 300,
    "PUSH_WORKER_POLL_SECONDS": 3,
}

INSPECTED_SETTINGS = [
    "DEBUG",
    "ALLOWED_HOSTS",
    "FRONTEND_ORIGINS",
    "BACKEND_ORIGINS",
    "CORS_ALLOWED_ORIGINS",
    "CORS_ALLOWED_ORIGIN_REGEXES",
    "CORS_ALLOW_ALL_ORIGINS",
    "CORS_ALLOW_CREDENTIALS",
    "CSRF_TRUSTED_ORIGINS",
    "SECURE_PROXY_SSL_HEADER",
    "SECURE_SSL_REDIRECT",
    "SECURE_CONTENT_TYPE_NOSNIFF",
    "SECURE_REFERRER_POLICY",
    "X_FRAME_OPTIONS",
    "SECURE_HSTS_SECONDS",
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    "SECURE_HSTS_PRELOAD",
    "SESSION_COOKIE_SECURE",
    "SESSION_COOKIE_NAME",
    "CSRF_COOKIE_SECURE",
    "CSRF_COOKIE_HTTPONLY",
    "CSRF_COOKIE_NAME",
    "CSRF_COOKIE_SAMESITE",
    "JWT_COOKIE_SECURE",
    "JWT_COOKIE_HTTPONLY",
    "JWT_COOKIE_SAMESITE",
    "JWT_COOKIE_DOMAIN",
    "JWT_ACCESS_COOKIE_NAME",
    "JWT_REFRESH_COOKIE_NAME",
    "JWT_ACCESS_COOKIE_PATH",
    "JWT_REFRESH_COOKIE_PATH",
    "STATIC_URL",
    "STORAGES",
    "MEDIA_URL",
    "MEDIA_ROOT",
    "FIREBASE_PUSH_ENABLED",
    "FIREBASE_PROJECT_ID",
    "FIREBASE_HTTP_TIMEOUT_SECONDS",
    "PUSH_SEND_CHUNK_SIZE",
    "PUSH_MAX_ATTEMPTS",
    "PUSH_MAX_AGE_HOURS",
    "PUSH_WORKER_BATCH_SIZE",
    "PUSH_LEASE_SECONDS",
    "PUSH_WORKER_POLL_SECONDS",
    "ANNOUNCEMENT_NOTIFY_HOUR",
    "API_DOCS_ENABLED",
    "SPECTACULAR_SETTINGS",
    "CACHES",
    "REST_FRAMEWORK",
    "ADMIN_URL_PATH",
]

# يعطّل قراءة ملف .env المحلي ثم يستورد وحدة الإعدادات ويطبع ملخصًا JSON
# لا يحتوي أي Secret.
SETTINGS_PROBE_SCRIPT = """
import importlib
import json
import sys

import environ

environ.Env.read_env = classmethod(lambda cls, *args, **kwargs: None)

from django.core.exceptions import ImproperlyConfigured

module_name = sys.argv[1]
inspected_settings = json.loads(sys.argv[2])

try:
    module = importlib.import_module(module_name)
except ImproperlyConfigured as error:
    print(json.dumps({"error": str(error)}))
    sys.exit(0)

database = dict(module.DATABASES["default"])
database.pop("PASSWORD", None)

print(json.dumps({
    "settings": {
        name: getattr(module, name)
        for name in inspected_settings
        if hasattr(module, name)
    },
    "database": database,
    "production_settings_loaded": "config.production_settings" in sys.modules,
}, default=str))
"""


def load_settings_module(module_name, environment):
    process_environment = {
        key: value
        for key, value in os.environ.items()
        if key not in MANAGED_ENVIRONMENT_VARIABLES
    }
    process_environment.update(environment)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            SETTINGS_PROBE_SCRIPT,
            module_name,
            json.dumps(INSPECTED_SETTINGS),
        ],
        cwd=BASE_DIR,
        env=process_environment,
        capture_output=True,
        text=True,
        timeout=60,
    )

    if completed.returncode != 0:
        raise AssertionError(
            f"Settings probe for {module_name} crashed:\n{completed.stderr}"
        )

    result = json.loads(completed.stdout.strip().splitlines()[-1])
    result["raw_output"] = completed.stdout + completed.stderr
    return result


class ProductionSettingsTestMixin:
    def load_production(self, **overrides):
        environment = dict(VALID_PRODUCTION_ENVIRONMENT)
        for key, value in overrides.items():
            if value is None:
                environment.pop(key, None)
            else:
                environment[key] = value

        return load_settings_module("config.production_settings", environment)

    def assert_loads(self, **overrides):
        result = self.load_production(**overrides)
        self.assertNotIn("error", result, result.get("error"))
        return result["settings"]

    def assert_rejected(self, expected_variable=None, **overrides):
        result = self.load_production(**overrides)
        self.assertIn(
            "error",
            result,
            "Expected ImproperlyConfigured for overrides "
            f"{sorted(overrides)}.",
        )
        if expected_variable:
            self.assertIn(expected_variable, result["error"])
        return result


class ProductionSettingsValidConfigurationTests(
    ProductionSettingsTestMixin,
    SimpleTestCase,
):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.result = load_settings_module(
            "config.production_settings",
            VALID_PRODUCTION_ENVIRONMENT,
        )

    def setUp(self):
        self.assertNotIn("error", self.result, self.result.get("error"))
        self.settings = self.result["settings"]

    def test_debug_is_false(self):
        self.assertIs(self.settings["DEBUG"], False)

    def test_api_documentation_is_disabled(self):
        self.assertIs(self.settings["API_DOCS_ENABLED"], False)
        self.assertEqual(
            self.settings["SPECTACULAR_SETTINGS"],
            {
                "TITLE": "Asas School Academic API",
                "DESCRIPTION": "واجهة برمجة تطبيقات منصة مدرسة أساس الأكاديمية",
                "VERSION": "1.0.0",
                "SERVE_INCLUDE_SCHEMA": False,
                "COMPONENT_SPLIT_REQUEST": True,
            },
        )

    def test_exact_origins_are_accepted(self):
        self.assertEqual(self.settings["ALLOWED_HOSTS"], ["api.example.com"])
        self.assertEqual(
            self.settings["CORS_ALLOWED_ORIGINS"],
            ["https://app.example.com"],
        )
        self.assertEqual(
            self.settings["CSRF_TRUSTED_ORIGINS"],
            ["https://app.example.com", "https://api.example.com"],
        )
        self.assertIs(self.settings["CORS_ALLOW_CREDENTIALS"], True)
        self.assertIs(self.settings["CORS_ALLOW_ALL_ORIGINS"], False)

    def test_inherited_vercel_regex_is_removed(self):
        self.assertEqual(self.settings["CORS_ALLOWED_ORIGIN_REGEXES"], [])
        self.assertFalse(
            any(
                "vercel" in origin
                for origin in self.settings["CSRF_TRUSTED_ORIGINS"]
            )
        )

    def test_secure_cookies_are_enforced(self):
        self.assertIs(self.settings["SESSION_COOKIE_SECURE"], True)
        self.assertIs(self.settings["CSRF_COOKIE_SECURE"], True)
        self.assertIs(self.settings["JWT_COOKIE_SECURE"], True)
        self.assertIs(self.settings["JWT_COOKIE_HTTPONLY"], True)
        self.assertIs(self.settings["CSRF_COOKIE_HTTPONLY"], True)
        self.assertEqual(self.settings["JWT_COOKIE_SAMESITE"], "None")
        self.assertEqual(self.settings["CSRF_COOKIE_SAMESITE"], "None")
        self.assertIsNone(self.settings["JWT_COOKIE_DOMAIN"])

    def test_cookie_names_and_paths_are_unchanged(self):
        self.assertEqual(self.settings["JWT_ACCESS_COOKIE_NAME"], "asas_web_access")
        self.assertEqual(
            self.settings["JWT_REFRESH_COOKIE_NAME"],
            "asas_web_refresh",
        )
        self.assertEqual(self.settings["JWT_ACCESS_COOKIE_PATH"], "/api/")
        self.assertEqual(
            self.settings["JWT_REFRESH_COOKIE_PATH"],
            "/api/v1/auth/web/",
        )
        self.assertEqual(self.settings["CSRF_COOKIE_NAME"], "asas_web_csrf")
        self.assertEqual(self.settings["SESSION_COOKIE_NAME"], "asas_admin_session")

    def test_https_proxy_settings(self):
        self.assertEqual(
            self.settings["SECURE_PROXY_SSL_HEADER"],
            ["HTTP_X_FORWARDED_PROTO", "https"],
        )
        self.assertIs(self.settings["SECURE_SSL_REDIRECT"], True)
        self.assertIs(self.settings["SECURE_CONTENT_TYPE_NOSNIFF"], True)
        self.assertEqual(self.settings["X_FRAME_OPTIONS"], "DENY")
        self.assertEqual(self.settings["SECURE_REFERRER_POLICY"], "same-origin")

    def test_hsts_defaults_to_zero(self):
        self.assertEqual(self.settings["SECURE_HSTS_SECONDS"], 0)
        self.assertIs(self.settings["SECURE_HSTS_INCLUDE_SUBDOMAINS"], False)
        self.assertIs(self.settings["SECURE_HSTS_PRELOAD"], False)

    def test_static_and_media_settings(self):
        self.assertEqual(
            set(self.settings["STORAGES"]),
            {"default", "staticfiles"},
        )
        self.assertEqual(
            self.settings["STORAGES"]["default"]["BACKEND"],
            "django.core.files.storage.FileSystemStorage",
        )
        self.assertEqual(self.settings["STATIC_URL"], "/static/")
        self.assertEqual(
            self.settings["STORAGES"]["staticfiles"]["BACKEND"],
            "whitenoise.storage.CompressedManifestStaticFilesStorage",
        )
        self.assertEqual(self.settings["MEDIA_URL"], "/media/")
        self.assertEqual(self.settings["MEDIA_ROOT"], "/srv/test-media")

    def test_database_uses_db_environment_variables(self):
        database = self.result["database"]
        self.assertEqual(database["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(database["NAME"], "asas_test")
        self.assertEqual(database["USER"], "asas_test_user")
        self.assertEqual(database["HOST"], "127.0.0.1")
        self.assertEqual(database["PORT"], 5432)
        self.assertEqual(database["OPTIONS"], {"sslmode": "disable"})
        self.assertNotIn(TEST_DB_PASSWORD, self.result["raw_output"])

    def test_firebase_disabled_by_default(self):
        self.assertIs(self.settings["FIREBASE_PUSH_ENABLED"], False)

    def test_push_worker_settings_have_defaults(self):
        self.assertEqual(
            {name: self.settings[name] for name in PUSH_WORKER_DEFAULTS},
            PUSH_WORKER_DEFAULTS,
        )

    def test_announcement_notify_hour_defaults_to_seven(self):
        self.assertEqual(self.settings["ANNOUNCEMENT_NOTIFY_HOUR"], 7)

    def test_default_cache_uses_postgresql_database_cache(self):
        caches = self.settings["CACHES"]

        self.assertEqual(set(caches), {"default"})
        self.assertEqual(
            caches["default"],
            {
                "BACKEND": "django.core.cache.backends.db.DatabaseCache",
                "LOCATION": "asas_cache",
                "TIMEOUT": 300,
                "KEY_PREFIX": "asas",
                "OPTIONS": {
                    "MAX_ENTRIES": 5000,
                    "CULL_FREQUENCY": 3,
                },
            },
        )

    def test_production_cache_does_not_use_redis_or_local_memory(self):
        backend = self.settings["CACHES"]["default"]["BACKEND"]

        self.assertNotIn("redis", backend.lower())
        self.assertNotIn("locmem", backend.lower())

    def test_rest_framework_keeps_inherited_settings_and_sets_one_proxy(self):
        rest_framework = self.settings["REST_FRAMEWORK"]

        self.assertEqual(rest_framework["NUM_PROXIES"], 1)
        self.assertEqual(
            rest_framework["DEFAULT_AUTHENTICATION_CLASSES"],
            ["accounts.authentication.CookieJWTAuthentication"],
        )
        self.assertEqual(
            rest_framework["DEFAULT_PERMISSION_CLASSES"],
            [
                "rest_framework.permissions.IsAuthenticated",
                "accounts.permissions.PasswordChangeGate",
            ],
        )
        self.assertEqual(
            rest_framework["DEFAULT_PAGINATION_CLASS"],
            "config.pagination.StandardPageNumberPagination",
        )
        self.assertEqual(
            rest_framework["DEFAULT_THROTTLE_RATES"],
            {
                "web_login": "5/minute",
                "mobile_login": "5/minute",
                "mobile_school_request_burst": "3/minute",
                "mobile_school_request_hourly": "5/hour",
                "mobile_appointment_request_burst": "3/minute",
                "mobile_appointment_request_hourly": "5/hour",
                "mobile_device_registration": "10/minute",
                "mobile_device_unregistration": "10/minute",
                "mobile_account_deletion": "5/hour",
            },
        )


class ProductionSettingsValidationTests(
    ProductionSettingsTestMixin,
    SimpleTestCase,
):
    def test_debug_true_is_rejected(self):
        self.assert_rejected("DEBUG", DEBUG="True")

    def test_debug_false_is_accepted(self):
        settings = self.assert_loads(DEBUG="False")
        self.assertIs(settings["DEBUG"], False)

    def test_origin_lists_are_normalized_and_deduplicated(self):
        settings = self.assert_loads(
            FRONTEND_ORIGINS=(
                "https://app.example.com,https://APP.example.com/,"
                "https://admin.example.com"
            ),
            BACKEND_ORIGINS="https://api.example.com,https://app.example.com",
        )
        self.assertEqual(
            settings["CORS_ALLOWED_ORIGINS"],
            ["https://app.example.com", "https://admin.example.com"],
        )
        self.assertEqual(
            settings["CSRF_TRUSTED_ORIGINS"],
            [
                "https://app.example.com",
                "https://admin.example.com",
                "https://api.example.com",
            ],
        )

    def test_wildcard_origins_are_rejected(self):
        for value in ("*", "https://*.example.com"):
            with self.subTest(value=value):
                self.assert_rejected("FRONTEND_ORIGINS", FRONTEND_ORIGINS=value)

    def test_loopback_origins_are_accepted_with_their_scheme(self):
        for value in (
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "https://localhost",
        ):
            with self.subTest(value=value):
                settings = self.assert_loads(FRONTEND_ORIGINS=value)
                self.assertEqual(settings["CORS_ALLOWED_ORIGINS"], [value])
                self.assertEqual(
                    settings["CSRF_TRUSTED_ORIGINS"],
                    [value, "https://api.example.com"],
                )

    def test_unspecified_address_origin_is_rejected(self):
        for value in ("http://0.0.0.0:3000", "https://0.0.0.0"):
            with self.subTest(value=value):
                self.assert_rejected("FRONTEND_ORIGINS", FRONTEND_ORIGINS=value)

    def test_http_origins_are_rejected(self):
        for value in ("http://app.example.com", "http://example.com"):
            with self.subTest(value=value):
                self.assert_rejected("FRONTEND_ORIGINS", FRONTEND_ORIGINS=value)
        self.assert_rejected(
            "BACKEND_ORIGINS",
            BACKEND_ORIGINS="http://api.example.com",
        )

    def test_full_vercel_origin_is_accepted(self):
        settings = self.assert_loads(
            FRONTEND_ORIGINS="https://assas-school.vercel.app",
        )
        self.assertEqual(
            settings["CORS_ALLOWED_ORIGINS"],
            ["https://assas-school.vercel.app"],
        )
        self.assertEqual(settings["CORS_ALLOWED_ORIGIN_REGEXES"], [])
        self.assertEqual(
            settings["CSRF_TRUSTED_ORIGINS"],
            ["https://assas-school.vercel.app", "https://api.example.com"],
        )

    def test_vercel_wildcard_and_bare_domain_are_rejected(self):
        for value in ("https://*.vercel.app", "https://vercel.app"):
            with self.subTest(value=value):
                self.assert_rejected("FRONTEND_ORIGINS", FRONTEND_ORIGINS=value)

    def test_origins_with_path_query_or_fragment_are_rejected(self):
        for value in (
            "https://app.example.com/dashboard",
            "https://app.example.com?next=1",
            "https://app.example.com#top",
        ):
            with self.subTest(value=value):
                self.assert_rejected("FRONTEND_ORIGINS", FRONTEND_ORIGINS=value)

    def test_backend_origins_use_same_rules(self):
        for value in (
            "https://*.example.com",
            "http://api.example.com",
            "https://api.example.com/api",
        ):
            with self.subTest(value=value):
                self.assert_rejected("BACKEND_ORIGINS", BACKEND_ORIGINS=value)

    def test_invalid_allowed_hosts_are_rejected(self):
        for value in (
            "https://api.example.com",
            "api.example.com/path",
            "api.example.com?x=1",
            "*",
            "*.example.com",
            ".example.com",
            "localhost",
            "127.0.0.1",
            "api.example.com, ,admin.example.com",
            "api.example.com:8000",
            "bad_host!.example.com",
        ):
            with self.subTest(value=value):
                self.assert_rejected("ALLOWED_HOSTS", ALLOWED_HOSTS=value)

    def test_missing_required_variables_are_rejected(self):
        for name in (
            "SECRET_KEY",
            "JWT_SIGNING_KEY",
            "ALLOWED_HOSTS",
            "FRONTEND_ORIGINS",
            "BACKEND_ORIGINS",
            "DB_NAME",
            "DB_USER",
            "DB_PASSWORD",
            "DB_HOST",
            "DB_PORT",
            "DB_SSLMODE",
            "MEDIA_ROOT",
            "ADMIN_URL_PATH",
        ):
            for value in (None, ""):
                with self.subTest(name=name, value=value):
                    self.assert_rejected(name, **{name: value})

    def test_weak_secret_keys_are_rejected(self):
        self.assert_rejected("SECRET_KEY", SECRET_KEY="too-short")
        self.assert_rejected(
            "SECRET_KEY",
            SECRET_KEY="django-insecure-" + "x" * 60,
        )
        self.assert_rejected("JWT_SIGNING_KEY", JWT_SIGNING_KEY="too-short")
        self.assert_rejected("JWT_SIGNING_KEY", JWT_SIGNING_KEY=TEST_SECRET_KEY)

    def test_relative_media_root_is_rejected(self):
        for value in ("media", "./media", "var/www/asas/media", "/srv/../etc", "/"):
            with self.subTest(value=value):
                self.assert_rejected("MEDIA_ROOT", MEDIA_ROOT=value)

    def test_admin_url_path_is_read_from_environment(self):
        for value in ("manage-x7k2/", "api-panel/", "Panel_9/"):
            with self.subTest(value=value):
                settings = self.assert_loads(ADMIN_URL_PATH=value)
                self.assertEqual(settings["ADMIN_URL_PATH"], value)

    def test_default_admin_url_path_is_rejected(self):
        for value in ("admin/", "Admin/", "ADMIN/"):
            with self.subTest(value=value):
                self.assert_rejected("ADMIN_URL_PATH", ADMIN_URL_PATH=value)

    def test_invalid_admin_url_paths_are_rejected(self):
        for value in (
            "/x/",
            "x",
            "a/b/",
            "api/x/",
            "api/",
            "Health/",
            "static/",
            "media/",
            "إدارة/",
            "my panel/",
            "panel.x/",
        ):
            with self.subTest(value=value):
                self.assert_rejected("ADMIN_URL_PATH", ADMIN_URL_PATH=value)

    def test_media_url_stays_fixed(self):
        settings = self.assert_loads(MEDIA_URL="/uploads/")
        self.assertEqual(settings["MEDIA_URL"], "/media/")

    def test_invalid_db_port_is_rejected(self):
        for value in ("abc", "0", "65536", "-1", "54.32"):
            with self.subTest(value=value):
                self.assert_rejected("DB_PORT", DB_PORT=value)

    def test_invalid_db_sslmode_is_rejected(self):
        self.assert_rejected("DB_SSLMODE", DB_SSLMODE="sometimes")

    def test_db_sslmode_is_not_forced(self):
        result = self.load_production(DB_SSLMODE="require")
        self.assertEqual(result["database"]["OPTIONS"], {"sslmode": "require"})

    def test_invalid_hsts_values_are_rejected(self):
        for value in ("-1", "abc", "1.5"):
            with self.subTest(value=value):
                self.assert_rejected(
                    "SECURE_HSTS_SECONDS",
                    SECURE_HSTS_SECONDS=value,
                )

    def test_hsts_is_configurable(self):
        settings = self.assert_loads(SECURE_HSTS_SECONDS="3600")
        self.assertEqual(settings["SECURE_HSTS_SECONDS"], 3600)

    def test_hsts_preload_requires_full_hsts(self):
        self.assert_rejected(
            "SECURE_HSTS_PRELOAD",
            SECURE_HSTS_PRELOAD="True",
            SECURE_HSTS_SECONDS="3600",
            SECURE_HSTS_INCLUDE_SUBDOMAINS="True",
        )

    def test_samesite_values(self):
        settings = self.assert_loads(
            JWT_COOKIE_SAMESITE="Strict",
            CSRF_COOKIE_SAMESITE="none",
        )
        self.assertEqual(settings["JWT_COOKIE_SAMESITE"], "Strict")
        self.assertEqual(settings["CSRF_COOKIE_SAMESITE"], "None")
        self.assertIs(settings["CSRF_COOKIE_SECURE"], True)

        self.assert_rejected("JWT_COOKIE_SAMESITE", JWT_COOKIE_SAMESITE="Loose")

    def test_explicit_lax_samesite_is_respected(self):
        settings = self.assert_loads(
            JWT_COOKIE_SAMESITE="Lax",
            CSRF_COOKIE_SAMESITE="Lax",
        )
        self.assertEqual(settings["JWT_COOKIE_SAMESITE"], "Lax")
        self.assertEqual(settings["CSRF_COOKIE_SAMESITE"], "Lax")

    def test_samesite_none_with_insecure_cookie_is_rejected(self):
        self.assert_rejected(
            "JWT_COOKIE_SECURE",
            JWT_COOKIE_SAMESITE="None",
            JWT_COOKIE_SECURE="False",
        )
        self.assert_rejected(
            "CSRF_COOKIE_SECURE",
            CSRF_COOKIE_SAMESITE="None",
            CSRF_COOKIE_SECURE="False",
        )

    def test_disabling_secure_cookies_is_rejected(self):
        self.assert_rejected(
            "JWT_COOKIE_SECURE",
            JWT_COOKIE_SAMESITE="Lax",
            JWT_COOKIE_SECURE="False",
        )

    def test_explicit_cookie_domain(self):
        settings = self.assert_loads(JWT_COOKIE_DOMAIN="api.example.com")
        self.assertEqual(settings["JWT_COOKIE_DOMAIN"], "api.example.com")

        for value in ("https://example.com", "localhost", "example.com/path"):
            with self.subTest(value=value):
                self.assert_rejected(
                    "JWT_COOKIE_DOMAIN",
                    JWT_COOKIE_DOMAIN=value,
                )

    def test_enabled_push_requires_firebase_settings(self):
        self.assert_rejected(
            "FIREBASE_PROJECT_ID",
            FIREBASE_PUSH_ENABLED="True",
            GOOGLE_APPLICATION_CREDENTIALS="/srv/test-credentials.json",
        )
        self.assert_rejected(
            "GOOGLE_APPLICATION_CREDENTIALS",
            FIREBASE_PUSH_ENABLED="True",
            FIREBASE_PROJECT_ID="test-project",
        )

    def test_enabled_push_with_settings_is_accepted(self):
        settings = self.assert_loads(
            FIREBASE_PUSH_ENABLED="True",
            FIREBASE_PROJECT_ID="test-project",
            GOOGLE_APPLICATION_CREDENTIALS="/srv/test-credentials.json",
        )
        self.assertIs(settings["FIREBASE_PUSH_ENABLED"], True)

    def test_push_worker_settings_are_configurable(self):
        overrides = {
            name: str(value + 1) for name, value in PUSH_WORKER_DEFAULTS.items()
        }
        settings = self.assert_loads(**overrides)
        self.assertEqual(
            {name: settings[name] for name in PUSH_WORKER_DEFAULTS},
            {name: value + 1 for name, value in PUSH_WORKER_DEFAULTS.items()},
        )

    def test_invalid_push_worker_settings_are_rejected(self):
        for name in PUSH_WORKER_DEFAULTS:
            for value in ("0", "-5", "not-a-number"):
                with self.subTest(name=name, value=value):
                    self.assert_rejected(name, **{name: value})

        # send_each accepts at most 500 messages per call.
        self.assert_rejected("PUSH_SEND_CHUNK_SIZE", PUSH_SEND_CHUNK_SIZE="501")
        settings = self.assert_loads(PUSH_SEND_CHUNK_SIZE="500")
        self.assertEqual(settings["PUSH_SEND_CHUNK_SIZE"], 500)

    def test_announcement_notify_hour_accepts_every_hour_of_the_day(self):
        for value in ("0", "23"):
            with self.subTest(value=value):
                settings = self.assert_loads(ANNOUNCEMENT_NOTIFY_HOUR=value)
                self.assertEqual(settings["ANNOUNCEMENT_NOTIFY_HOUR"], int(value))

    def test_invalid_announcement_notify_hour_is_rejected(self):
        for value in ("24", "-1", "abc"):
            with self.subTest(value=value):
                self.assert_rejected(
                    "ANNOUNCEMENT_NOTIFY_HOUR", ANNOUNCEMENT_NOTIFY_HOUR=value,
                )

    def test_sensitive_values_do_not_appear_in_errors(self):
        short_secret = "short-secret-sentinel-value"
        result = self.assert_rejected("SECRET_KEY", SECRET_KEY=short_secret)
        self.assertNotIn(short_secret, result["raw_output"])

        result = self.assert_rejected(
            "JWT_SIGNING_KEY",
            JWT_SIGNING_KEY=TEST_SECRET_KEY,
        )
        self.assertNotIn(TEST_SECRET_KEY, result["raw_output"])

        result = self.assert_rejected("DB_PORT", DB_PORT="not-a-port-sentinel")
        self.assertNotIn("not-a-port-sentinel", result["raw_output"])
        self.assertNotIn(TEST_DB_PASSWORD, result["raw_output"])

        result = self.assert_rejected("MEDIA_ROOT", MEDIA_ROOT="")
        self.assertEqual(
            result["error"],
            "MEDIA_ROOT is required in production.",
        )
        for secret in (TEST_SECRET_KEY, TEST_JWT_SIGNING_KEY, TEST_DB_PASSWORD):
            self.assertNotIn(secret, result["raw_output"])


class BaseSettingsUnchangedTests(SimpleTestCase):
    def test_development_settings_keep_existing_behavior(self):
        result = load_settings_module("config.settings", DEVELOPMENT_ENVIRONMENT)

        self.assertNotIn("error", result, result.get("error"))
        self.assertIs(result["production_settings_loaded"], False)
        settings = result["settings"]
        self.assertIs(settings["DEBUG"], True)
        self.assertIs(settings["API_DOCS_ENABLED"], True)
        self.assertEqual(settings["ALLOWED_HOSTS"], ["127.0.0.1", "localhost"])
        self.assertEqual(
            settings["CORS_ALLOWED_ORIGIN_REGEXES"],
            [r"^https://[A-Za-z0-9-]+\.vercel\.app$"],
        )
        self.assertIn("https://*.vercel.app", settings["CSRF_TRUSTED_ORIGINS"])
        self.assertIs(settings["SECURE_SSL_REDIRECT"], False)
        self.assertIs(settings["JWT_COOKIE_SECURE"], False)
        self.assertEqual(settings["JWT_COOKIE_SAMESITE"], "Lax")
        self.assertEqual(settings["ADMIN_URL_PATH"], "admin/")
        self.assertNotIn("STORAGES", settings)
        self.assertEqual(settings["MEDIA_ROOT"], str(BASE_DIR / "media"))
        self.assertEqual(settings["MEDIA_URL"], "/media/")
        self.assertNotIn("CACHES", settings)
        self.assertNotIn("NUM_PROXIES", settings["REST_FRAMEWORK"])
        self.assertEqual(result["database"]["OPTIONS"], {"sslmode": "disable"})

    def test_test_settings_keep_existing_behavior(self):
        result = load_settings_module(
            "config.test_settings",
            DEVELOPMENT_ENVIRONMENT,
        )

        self.assertNotIn("error", result, result.get("error"))
        self.assertIs(result["production_settings_loaded"], False)
        self.assertIs(result["settings"]["API_DOCS_ENABLED"], True)
        self.assertEqual(
            result["database"],
            {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"},
        )
        self.assertEqual(
            result["settings"]["CORS_ALLOWED_ORIGIN_REGEXES"],
            [r"^https://[A-Za-z0-9-]+\.vercel\.app$"],
        )
        self.assertEqual(
            result["settings"]["MEDIA_ROOT"],
            str(BASE_DIR / "media"),
        )
        self.assertEqual(result["settings"]["MEDIA_URL"], "/media/")
        self.assertNotIn("CACHES", result["settings"])
        self.assertNotIn(
            "NUM_PROXIES",
            result["settings"]["REST_FRAMEWORK"],
        )
