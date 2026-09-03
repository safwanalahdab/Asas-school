import uuid
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from firebase_admin import messaging

from notifications.models import Notification, PushDevice
from notifications.push_services import (
    PushDeliveryResult,
    build_notification_message,
    safe_send_notification_push,
    send_notification_push,
)
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
        self.other = User.objects.create_user(
            username="push-other",
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

    def device(self, *, user=None, active=True, token=None):
        return PushDevice.objects.create(
            user=user or self.guardian,
            installation_id=uuid.uuid4(),
            fcm_token=token or f"token-{uuid.uuid4()}",
            platform=PushDevice.Platform.ANDROID,
            is_active=active,
            last_seen_at=timezone.now(),
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

    @override_settings(FIREBASE_PUSH_ENABLED=False)
    @patch("notifications.push_services.get_firebase_app")
    @patch("notifications.push_services.messaging.send")
    def test_disabled_never_initializes_or_sends(self, send, get_app):
        self.device()
        self.assertEqual(send_notification_push(self.notification), PushDeliveryResult())
        get_app.assert_not_called()
        send.assert_not_called()

    @override_settings(FIREBASE_PUSH_ENABLED=True)
    @patch("notifications.push_services.get_firebase_app", return_value=object())
    @patch("notifications.push_services.messaging.send", return_value="message-id")
    def test_only_active_recipient_devices_are_sent(self, send, _get_app):
        self.device()
        self.device(active=False)
        self.device(user=self.other)
        result = send_notification_push(self.notification)
        self.assertEqual(result, PushDeliveryResult(attempted=1, sent=1))
        self.assertEqual(send.call_count, 1)

    @override_settings(FIREBASE_PUSH_ENABLED=True)
    @patch("notifications.push_services.get_firebase_app", return_value=object())
    @patch("notifications.push_services.messaging.send", return_value="message-id")
    def test_two_active_devices_receive_independent_attempts(self, send, _get_app):
        self.device()
        self.device()
        result = send_notification_push(self.notification)
        self.assertEqual(result, PushDeliveryResult(attempted=2, sent=2))
        self.assertEqual(send.call_count, 2)

    @override_settings(FIREBASE_PUSH_ENABLED=True)
    @patch("notifications.push_services.get_firebase_app", return_value=object())
    @patch("notifications.push_services.messaging.send")
    def test_unregistered_device_is_disabled_and_other_device_continues(
        self, send, _get_app
    ):
        invalid = self.device(token="invalid-token")
        valid = self.device(token="valid-token")
        def send_one(message, **_kwargs):
            if message.token == "invalid-token":
                raise messaging.UnregisteredError("unregistered")
            return "message-id"

        send.side_effect = send_one
        result = send_notification_push(self.notification)
        invalid.refresh_from_db()
        valid.refresh_from_db()
        self.assertEqual(
            result, PushDeliveryResult(attempted=2, sent=1, failed=1, disabled=1)
        )
        self.assertFalse(invalid.is_active)
        self.assertTrue(valid.is_active)
        self.assertTrue(Notification.objects.filter(pk=self.notification.pk).exists())

    @override_settings(FIREBASE_PUSH_ENABLED=True)
    @patch("notifications.push_services.get_firebase_app", return_value=object())
    @patch("notifications.push_services.messaging.send", side_effect=RuntimeError("down"))
    def test_transient_failure_is_contained_without_disabling_device(
        self, _send, _get_app
    ):
        device = self.device()
        result = safe_send_notification_push(self.notification.id)
        device.refresh_from_db()
        self.assertEqual(result, PushDeliveryResult(attempted=1, failed=1))
        self.assertTrue(device.is_active)
        self.assertTrue(Notification.objects.filter(pk=self.notification.pk).exists())

    @override_settings(FIREBASE_PUSH_ENABLED=True)
    @patch("notifications.push_services.get_firebase_app", side_effect=RuntimeError("config"))
    def test_initialization_failure_is_contained(self, _get_app):
        self.device()
        self.assertEqual(
            safe_send_notification_push(self.notification.id),
            PushDeliveryResult(attempted=1, failed=1),
        )

    @override_settings(FIREBASE_PUSH_ENABLED=True)
    @patch("notifications.push_services.messaging.send")
    def test_no_devices_and_ineligible_recipient_do_not_send(self, send):
        self.assertEqual(send_notification_push(self.notification), PushDeliveryResult())
        self.guardian.must_change_password = True
        self.guardian.save(update_fields=["must_change_password"])
        self.notification.recipient.must_change_password = True
        self.device()
        self.assertEqual(send_notification_push(self.notification), PushDeliveryResult())
        send.assert_not_called()
        self.assertTrue(Notification.objects.filter(pk=self.notification.pk).exists())


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

    @patch("notifications.push_services.safe_send_notification_push")
    def test_new_event_schedules_once_and_duplicate_does_not(self, safe_send):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            first, first_created = self.create("push:event:1")
            second, second_created = self.create("push:event:1")
            safe_send.assert_not_called()
        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(len(callbacks), 1)
        safe_send.assert_called_once_with(first.id)

    @patch("notifications.push_services.safe_send_notification_push")
    def test_rollback_discards_callback(self, safe_send):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            try:
                with transaction.atomic():
                    self.create("push:rollback")
                    raise RuntimeError("rollback")
            except RuntimeError:
                pass
        self.assertEqual(callbacks, [])
        safe_send.assert_not_called()
        self.assertFalse(Notification.objects.filter(event_key="push:rollback").exists())
