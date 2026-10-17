from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase
from django.urls import reverse

from config.settings import validate_admin_url_path


class AdminUrlPathTests(SimpleTestCase):
    def test_admin_index_uses_configured_path(self):
        self.assertEqual(reverse("admin:index"), "/" + settings.ADMIN_URL_PATH)

    def test_valid_paths_are_accepted(self):
        for value in ("admin/", "manage-x7k2/", "api-panel/", "Panel_9/"):
            with self.subTest(value=value):
                self.assertEqual(validate_admin_url_path(value), value)

    def test_invalid_paths_are_rejected(self):
        for value in (
            "",
            "/x/",
            "x",
            "a/b/",
            "api/x/",
            "API/",
            "health/",
            "static/",
            "media/",
            "إدارة/",
            "my panel/",
            "panel/\n",
        ):
            with self.subTest(value=value):
                with self.assertRaisesMessage(
                    ImproperlyConfigured,
                    "ADMIN_URL_PATH",
                ):
                    validate_admin_url_path(value)
