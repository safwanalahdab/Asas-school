import importlib
from contextlib import contextmanager

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.urls import Resolver404, clear_url_caches, resolve, reverse

from config import urls as project_urls


@contextmanager
def reloaded_project_urls(*, enabled):
    override = override_settings(API_DOCS_ENABLED=enabled)
    override.enable()
    clear_url_caches()
    importlib.reload(project_urls)
    try:
        yield
    finally:
        override.disable()
        clear_url_caches()
        importlib.reload(project_urls)
        clear_url_caches()


class ApiDocumentationUrlTests(SimpleTestCase):
    documentation_routes = {
        "api-schema": "/api/schema/",
        "swagger-ui": "/api/docs/",
        "redoc": "/api/redoc/",
    }

    def test_documentation_routes_are_registered_when_enabled(self):
        with reloaded_project_urls(enabled=True):
            for route_name, expected_path in self.documentation_routes.items():
                with self.subTest(route_name=route_name):
                    self.assertEqual(reverse(route_name), expected_path)
                    self.assertEqual(resolve(expected_path).url_name, route_name)

    def test_documentation_routes_return_404_when_disabled(self):
        with reloaded_project_urls(enabled=False):
            for route_name, path in self.documentation_routes.items():
                with self.subTest(route_name=route_name):
                    with self.assertRaises(Resolver404):
                        resolve(path)
                    self.assertEqual(self.client.get(path).status_code, 404)

    def test_core_routes_remain_registered_when_documentation_is_disabled(self):
        with reloaded_project_urls(enabled=False):
            self.assertEqual(resolve("/health/").url_name, "health-check")
            self.assertEqual(
                resolve("/api/v1/auth/web/login/").url_name,
                "web-login",
            )

    def test_spectacular_settings_are_unchanged_when_docs_are_enabled(self):
        with reloaded_project_urls(enabled=True):
            self.assertEqual(
                settings.SPECTACULAR_SETTINGS,
                {
                    "TITLE": "Asas School Academic API",
                    "DESCRIPTION": "واجهة برمجة تطبيقات منصة مدرسة أساس الأكاديمية",
                    "VERSION": "1.0.0",
                    "SERVE_INCLUDE_SCHEMA": False,
                    "COMPONENT_SPLIT_REQUEST": True,
                },
            )
