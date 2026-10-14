import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from notifications.models import Notification
from notifications.push_services import build_notification_message
from notifications.services import create_notification


User = get_user_model()


@override_settings(FIREBASE_PUSH_ENABLED=True, FIREBASE_PROJECT_ID="test-project")
class FirebaseInitializationTests(TestCase):
    def tearDown(self):
        from notifications import firebase_client

        firebase_client._firebase_app = None

    @override_settings(FIREBASE_PUSH_ENABLED=False)
    @patch("firebase_admin.initialize_app")
    def test_disabled_does_not_initialize(self, initialize_app):
        from notifications.firebase_client import get_firebase_app

        self.assertIsNone(get_firebase_app())
        initialize_app.assert_not_called()

    @patch("firebase_admin.initialize_app")
    @patch("firebase_admin.get_app", side_effect=ValueError)
    def test_lazy_initialization_uses_adc_project_and_runs_once(
        self, get_app, initialize_app
    ):
        from notifications.firebase_client import get_firebase_app

        firebase_app = object()
        initialize_app.return_value = firebase_app
        self.assertIs(get_firebase_app(), firebase_app)
        self.assertIs(get_firebase_app(), firebase_app)
        initialize_app.assert_called_once_with(options={"projectId": "test-project"})
        get_app.assert_called_once()


class PushServiceTests(TestCase):
    def setUp(self):
        self.guardian = User.objects.create_user(
            username="push-guardian",
            password="StrongPass!493",
            role=User.Role.GUARDIAN,
            must_change_password=False,
        )
        self.notification = Notification.objects.create(
            recipient=self.guardian,
            notification_type=Notification.NotificationType.APPOINTMENT,
            title="Safe title",
            body="Safe body",
            resource_type="appointment",
            resource_id=uuid.uuid4(),
        )

    def test_payload_is_safe_complete_and_all_data_values_are_strings(self):
        message = build_notification_message(
            notification=self.notification,
            token="target-token",
        )
        self.assertEqual(message.notification.title, "Safe title")
        self.assertEqual(message.notification.body, "Safe body")
        self.assertEqual(message.token, "target-token")
        self.assertEqual(
            message.data,
            {
                "notification_id": str(self.notification.id),
                "type": "appointment",
                "student_id": "",
                "resource_type": "appointment",
                "resource_id": str(self.notification.resource_id),
            },
        )
        self.assertTrue(all(isinstance(value, str) for value in message.data.values()))
        self.assertTrue(
            {"decision_reason", "school_response", "guardian", "username"}.isdisjoint(
                message.data
            )
        )

    def test_payload_uses_empty_strings_for_null_navigation_values(self):
        notification = Notification.objects.create(
            recipient=self.guardian,
            notification_type=Notification.NotificationType.GENERAL,
            title="General",
            body="Body",
        )
        data = build_notification_message(
            notification=notification, token="token"
        ).data
        self.assertEqual(data["student_id"], "")
        self.assertEqual(data["resource_type"], "")
        self.assertEqual(data["resource_id"], "")


@override_settings(FIREBASE_PUSH_ENABLED=True)
class PushSchedulingTests(TestCase):
    def setUp(self):
        self.guardian = User.objects.create_user(
            username="schedule-guardian",
            password="StrongPass!493",
            role=User.Role.GUARDIAN,
            must_change_password=False,
        )

    def create(self, event_key):
        return create_notification(
            recipient=self.guardian,
            notification_type=Notification.NotificationType.GENERAL,
            title="Title",
            body="Body",
            event_key=event_key,
        )

    @patch("firebase_admin.messaging.send_each")
    @patch("firebase_admin.messaging.send")
    def test_new_event_is_pending_once_and_never_sends(self, send, send_each):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            first, first_created = self.create("push:event:1")
            second, second_created = self.create("push:event:1")
        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(callbacks, [])
        first.refresh_from_db()
        self.assertEqual(first.push_status, Notification.PushStatus.PENDING)
        self.assertEqual(first.push_attempts, 0)
        self.assertIsNotNone(first.push_next_attempt_at)
        self.assertLessEqual(first.push_next_attempt_at, timezone.now())
        self.assertEqual(Notification.objects.filter(event_key="push:event:1").count(), 1)
        send.assert_not_called()
        send_each.assert_not_called()

    @override_settings(FIREBASE_PUSH_ENABLED=False)
    def test_disabled_push_creates_skipped_notification(self):
        notification, created = self.create("push:disabled")
        self.assertTrue(created)
        notification.refresh_from_db()
        self.assertEqual(notification.push_status, Notification.PushStatus.SKIPPED)

    @patch("firebase_admin.messaging.send_each")
    @patch("firebase_admin.messaging.send")
    def test_rollback_leaves_no_row(self, send, send_each):
        with self.assertRaises(RuntimeError), transaction.atomic():
            self.create("push:rollback")
            raise RuntimeError("rollback")
        self.assertFalse(Notification.objects.filter(event_key="push:rollback").exists())
        send.assert_not_called()
        send_each.assert_not_called()
