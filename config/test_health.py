from unittest.mock import patch

from django.db import OperationalError
from django.test import SimpleTestCase
from django.urls import reverse


class HealthCheckTests(SimpleTestCase):
    def setUp(self):
        self.url = reverse("health-check")

    @patch("config.health.connection")
    def test_get_returns_healthy_response_when_database_probe_succeeds(
        self, connection_mock
    ):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "success": True,
                "code": "HEALTH_CHECK_OK",
                "message": "الخدمة تعمل بشكل طبيعي.",
                "data": {"status": "healthy"},
            },
        )
        cursor = connection_mock.cursor.return_value.__enter__.return_value
        cursor.execute.assert_called_once_with("SELECT 1")

    @patch("config.health.connection")
    def test_get_does_not_require_authentication(self, connection_mock):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

    @patch("config.health.connection")
    def test_head_is_allowed(self, connection_mock):
        response = self.client.head(self.url)

        self.assertEqual(response.status_code, 200)

    def test_post_is_not_allowed(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 405)

    @patch("config.health.connection")
    def test_database_failure_returns_unhealthy_response(self, connection_mock):
        connection_mock.cursor.side_effect = OperationalError("database unavailable")

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "code": "HEALTH_CHECK_FAILED",
                "message": "الخدمة غير جاهزة حالياً.",
                "data": {"status": "unhealthy"},
            },
        )

    @patch("config.health.connection")
    def test_database_failure_does_not_expose_sensitive_details(
        self, connection_mock
    ):
        connection_mock.cursor.side_effect = OperationalError(
            "host=fake-db.internal password=super-secret"
        )

        response = self.client.get(self.url)
        response_text = response.content.decode()

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("fake-db.internal", response_text)
        self.assertNotIn("super-secret", response_text)
