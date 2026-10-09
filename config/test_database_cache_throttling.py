"""Login throttling against Django's real DatabaseCache backend.

These tests swap the default cache for the production DatabaseCache
configuration and create the `asas_cache` table inside the test database only.
The table is created within the class-level transaction of `TestCase`, so it is
rolled back after the class and never touches a real database.

Backend coverage:

- With `config.test_settings` (SQLite in memory) the throttling tests run
  against DatabaseCache on SQLite. This does not prove PostgreSQL behavior.
- With `config.settings` and the `DB_*` variables pointing to a PostgreSQL
  server where the user may create the `test_<DB_NAME>` database, the same
  tests run on PostgreSQL and the PostgreSQL-only checks are enabled.

Neither mode exercises concurrent requests or separate Gunicorn processes.
"""

from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.core.cache.backends.db import DatabaseCache
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.throttles import MobileLoginRateThrottle, WebLoginRateThrottle


User = get_user_model()

CACHE_TABLE = "asas_cache"

PRODUCTION_DATABASE_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": CACHE_TABLE,
        "TIMEOUT": 300,
        "KEY_PREFIX": "asas",
        "OPTIONS": {
            "MAX_ENTRIES": 300,
            "CULL_FREQUENCY": 3,
        },
    },
}

WEB_LOGIN_URL = "/api/v1/auth/web/login/"
MOBILE_LOGIN_URL = "/api/v1/auth/mobile/login/"


def cache_table_keys():
    table = connection.ops.quote_name(CACHE_TABLE)
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT cache_key FROM {table}")
        return [row[0] for row in cursor.fetchall()]


@override_settings(CACHES=PRODUCTION_DATABASE_CACHES)
class DatabaseCacheLoginThrottleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Runs inside the class transaction of the isolated test database.
        call_command("createcachetable", verbosity=0)

    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def web_login(self, ip_address):
        return self.client.post(
            WEB_LOGIN_URL,
            {"identifier": "throttle-web-user", "password": "wrong"},
            format="json",
            REMOTE_ADDR=ip_address,
        )

    def mobile_login(self, ip_address):
        return self.client.post(
            MOBILE_LOGIN_URL,
            {"identifier": "throttle-mobile-user", "password": "wrong"},
            format="json",
            REMOTE_ADDR=ip_address,
        )

    def assert_throttled_envelope(self, response):
        self.assertEqual(response.status_code, 429)
        self.assertIs(response.data["success"], False)
        self.assertEqual(response.data["code"], "TOO_MANY_REQUESTS")
        self.assertIn("message", response.data)
        self.assertIn("meta", response.data)

    def test_default_cache_is_database_cache(self):
        self.assertIsInstance(caches["default"], DatabaseCache)
        self.assertIs(WebLoginRateThrottle.cache, cache)
        self.assertIs(MobileLoginRateThrottle.cache, cache)
        self.assertIn(CACHE_TABLE, connection.introspection.table_names())

    def test_web_login_allows_five_attempts_then_returns_429(self):
        for attempt in range(5):
            with self.subTest(attempt=attempt + 1):
                self.assertEqual(self.web_login("203.0.113.10").status_code, 401)

        self.assert_throttled_envelope(self.web_login("203.0.113.10"))

    def test_mobile_login_allows_five_attempts_then_returns_429(self):
        for attempt in range(5):
            with self.subTest(attempt=attempt + 1):
                self.assertEqual(self.mobile_login("203.0.113.20").status_code, 401)

        self.assert_throttled_envelope(self.mobile_login("203.0.113.20"))

    def test_web_and_mobile_login_scopes_are_independent(self):
        ip_address = "203.0.113.30"
        for _ in range(5):
            self.web_login(ip_address)
        self.assertEqual(self.web_login(ip_address).status_code, 429)

        for attempt in range(5):
            with self.subTest(attempt=attempt + 1):
                self.assertEqual(self.mobile_login(ip_address).status_code, 401)
        self.assertEqual(self.mobile_login(ip_address).status_code, 429)

    def test_throttle_counters_are_stored_in_cache_table(self):
        self.web_login("203.0.113.40")
        self.mobile_login("203.0.113.40")

        keys = cache_table_keys()
        web_key = cache.make_key(
            WebLoginRateThrottle.cache_format
            % {"scope": "web_login", "ident": "203.0.113.40"}
        )
        mobile_key = cache.make_key(
            MobileLoginRateThrottle.cache_format
            % {"scope": "mobile_login", "ident": "203.0.113.40"}
        )
        self.assertIn(web_key, keys)
        self.assertIn(mobile_key, keys)
        self.assertTrue(web_key.startswith("asas:"))


@skipUnless(
    connection.vendor == "postgresql",
    "Requires a PostgreSQL test database (run with config.settings).",
)
@override_settings(CACHES=PRODUCTION_DATABASE_CACHES)
class PostgreSQLDatabaseCacheTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("createcachetable", verbosity=0)

    def setUp(self):
        cache.clear()

    def test_cache_table_exists_in_postgresql(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass(%s)::text", [CACHE_TABLE])
            self.assertEqual(cursor.fetchone()[0], CACHE_TABLE)

    def test_cache_read_write_round_trip(self):
        cache.set("health-probe", "ok", timeout=60)
        self.assertEqual(cache.get("health-probe"), "ok")
        self.assertIn(cache.make_key("health-probe"), cache_table_keys())

        cache.delete("health-probe")
        self.assertIsNone(cache.get("health-probe"))

    def test_login_throttle_returns_429_on_postgresql(self):
        client = APIClient()
        for _ in range(5):
            client.post(
                MOBILE_LOGIN_URL,
                {"identifier": "pg-user", "password": "wrong"},
                format="json",
                REMOTE_ADDR="203.0.113.50",
            )
        response = client.post(
            MOBILE_LOGIN_URL,
            {"identifier": "pg-user", "password": "wrong"},
            format="json",
            REMOTE_ADDR="203.0.113.50",
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data["code"], "TOO_MANY_REQUESTS")
