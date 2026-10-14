import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from firebase_admin import exceptions as firebase_exceptions
from firebase_admin import messaging

from notifications.models import Notification, PushDevice
from notifications.push_services import (
    PUSH_RETRY_DELAYS,
    build_notification_message,
    send_claimed_notifications,
)
from notifications.push_testing import fake_send_each, sent_tokens
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
        initialize_app.assert_called_once_with(
            options={"httpTimeout": 10, "projectId": "test-project"}
        )
        get_app.assert_called_once()

    @override_settings(FIREBASE_PROJECT_ID="", FIREBASE_HTTP_TIMEOUT_SECONDS=7)
    @patch("firebase_admin.initialize_app")
    @patch("firebase_admin.get_app", side_effect=ValueError)
    def test_http_timeout_comes_from_settings(self, _get_app, initialize_app):
        from notifications.firebase_client import get_firebase_app

        get_firebase_app()
        initialize_app.assert_called_once_with(options={"httpTimeout": 7})


@override_settings(FIREBASE_PUSH_ENABLED=True, PUSH_MAX_ATTEMPTS=6, PUSH_SEND_CHUNK_SIZE=50)
@patch("notifications.push_services.get_firebase_app", return_value=object())
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

    def device(self, *, user=None, active=True, token=None):
        return PushDevice.objects.create(
            user=user or self.guardian,
            installation_id=uuid.uuid4(),
            fcm_token=token or f"token-{uuid.uuid4()}",
            platform=PushDevice.Platform.ANDROID,
            is_active=active,
            last_seen_at=timezone.now(),
        )

    def send(self, notification=None):
        notification = Notification.objects.select_related("recipient").get(
            pk=(notification or self.notification).pk
        )
        result, = send_claimed_notifications([notification])
        return result

    def send_failing(self, errors_by_token, *, level="WARNING"):
        with patch(
            "notifications.push_services.messaging.send_each",
            side_effect=fake_send_each(errors_by_token),
        ), self.assertLogs("notifications.push_services", level=level) as logs:
            result = self.send()
        return result, "\n".join(logs.output)

    def test_payload_is_safe_complete_and_all_data_values_are_strings(self, _app):
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

    def test_payload_uses_empty_strings_for_null_navigation_values(self, _app):
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

    def test_payload_collapses_repeated_sends_on_android_and_ios(self, _app):
        message = build_notification_message(notification=self.notification, token="token")
        notification_id = str(self.notification.id)
        self.assertEqual(message.android.collapse_key, notification_id)
        self.assertEqual(message.android.notification.tag, notification_id)
        self.assertEqual(message.apns.headers, {"apns-collapse-id": notification_id})

    @override_settings(FIREBASE_PUSH_ENABLED=False)
    @patch("notifications.push_services.messaging.send_each")
    def test_disabled_is_skipped_without_initializing_or_sending(self, send_each, get_app):
        self.device()
        result = self.send()
        self.assertEqual(result.status, Notification.PushStatus.SKIPPED)
        self.assertEqual(result.attempts, 0)
        get_app.assert_not_called()
        send_each.assert_not_called()

    @patch("notifications.push_services.messaging.send_each")
    def test_ineligible_recipient_or_no_devices_is_skipped(self, send_each, _app):
        self.assertEqual(self.send().status, Notification.PushStatus.SKIPPED)
        self.device()
        for field, value in (("must_change_password", True), ("is_active", False)):
            with self.subTest(field=field):
                values = {"must_change_password": False, "is_active": True, field: value}
                User.objects.filter(pk=self.guardian.pk).update(**values)
                self.assertEqual(self.send().status, Notification.PushStatus.SKIPPED)
        send_each.assert_not_called()

    @patch("notifications.push_services.messaging.send_each", side_effect=fake_send_each())
    def test_success_sends_once_to_each_active_recipient_device(self, send_each, _app):
        first, second = self.device(), self.device()
        self.device(active=False)
        other = User.objects.create_user(
            username="push-other", password="StrongPass!493",
            role=User.Role.GUARDIAN, must_change_password=False,
        )
        self.device(user=other)

        before = timezone.now()
        result = self.send()

        self.assertEqual(result.status, Notification.PushStatus.SENT)
        self.assertEqual(result.attempts, 1)
        self.assertGreaterEqual(result.sent_at, before)
        self.assertEqual(result.error, "")
        self.assertCountEqual(result.delivered_device_ids, [str(first.id), str(second.id)])
        self.assertCountEqual(sent_tokens(send_each), [first.fcm_token, second.fcm_token])
        self.assertEqual(send_each.call_count, 1)

    def test_dead_tokens_are_disabled_and_other_device_still_counts(self, _app):
        for error in (
            messaging.UnregisteredError("unregistered"),
            messaging.SenderIdMismatchError("mismatch"),
        ):
            with self.subTest(error=type(error).__name__):
                PushDevice.objects.all().delete()
                dead, alive = self.device(), self.device()
                result, output = self.send_failing({dead.fcm_token: error})
                dead.refresh_from_db()
                alive.refresh_from_db()
                self.assertFalse(dead.is_active)
                self.assertTrue(alive.is_active)
                self.assertEqual(result.status, Notification.PushStatus.SENT)
                self.assertEqual(result.delivered_device_ids, [str(alive.id)])
                self.assertNotIn(dead.fcm_token, output)

    def test_invalid_argument_on_every_device_fails_permanently(self, _app):
        device = self.device()
        result, _output = self.send_failing(
            {device.fcm_token: firebase_exceptions.InvalidArgumentError("bad message")}
        )
        device.refresh_from_db()
        self.assertTrue(device.is_active)
        self.assertEqual(result.status, Notification.PushStatus.FAILED)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.error, "InvalidArgumentError")

    def test_transient_errors_retry_with_backoff(self, _app):
        errors = (
            firebase_exceptions.UnavailableError("unavailable"),
            firebase_exceptions.InternalError("internal"),
            messaging.QuotaExceededError("quota"),
            firebase_exceptions.DeadlineExceededError("timeout"),
            firebase_exceptions.UnknownError("unknown"),
            firebase_exceptions.NotFoundError("unexpected firebase error"),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                PushDevice.objects.all().delete()
                failing, ok = self.device(), self.device()
                before = timezone.now()
                result, _output = self.send_failing({failing.fcm_token: error})
                after = timezone.now()
                failing.refresh_from_db()
                self.assertTrue(failing.is_active)
                self.assertEqual(result.status, Notification.PushStatus.PENDING)
                self.assertEqual(result.attempts, 1)
                self.assertEqual(result.error, type(error).__name__)
                self.assertEqual(result.delivered_device_ids, [str(ok.id)])
                self.assertGreaterEqual(result.next_attempt_at, before + timedelta(seconds=30))
                self.assertLessEqual(result.next_attempt_at, after + timedelta(seconds=30))

    def test_configuration_errors_retry_and_log_at_error_level(self, _app):
        for error in (
            messaging.ThirdPartyAuthError("apns auth"),
            firebase_exceptions.PermissionDeniedError("denied"),
            firebase_exceptions.UnauthenticatedError("unauthenticated"),
        ):
            with self.subTest(error=type(error).__name__):
                PushDevice.objects.all().delete()
                device = self.device()
                result, output = self.send_failing({device.fcm_token: error}, level="ERROR")
                device.refresh_from_db()
                self.assertTrue(device.is_active)
                self.assertEqual(result.status, Notification.PushStatus.PENDING)
                self.assertIn(f"error={type(error).__name__}", output)
                self.assertNotIn(device.fcm_token, output)

    @patch("notifications.push_services.messaging.send_each", side_effect=fake_send_each())
    def test_retry_sends_only_to_devices_not_yet_delivered(self, send_each, _app):
        delivered, missing = self.device(), self.device()
        Notification.objects.filter(pk=self.notification.pk).update(
            push_attempts=1, push_delivered_device_ids=[str(delivered.id)],
        )
        result = self.send()
        self.assertEqual(sent_tokens(send_each), [missing.fcm_token])
        self.assertEqual(result.status, Notification.PushStatus.SENT)
        self.assertEqual(result.attempts, 2)
        self.assertCountEqual(result.delivered_device_ids, [str(delivered.id), str(missing.id)])

    @patch("notifications.push_services.messaging.send_each")
    def test_every_device_already_delivered_is_sent_without_calling_firebase(self, send_each, _app):
        device = self.device()
        Notification.objects.filter(pk=self.notification.pk).update(
            push_attempts=1, push_delivered_device_ids=[str(device.id)],
        )
        result = self.send()
        self.assertEqual(result.status, Notification.PushStatus.SENT)
        self.assertEqual(result.attempts, 1)
        send_each.assert_not_called()

    def test_retry_delays_follow_schedule_and_then_fail(self, _app):
        device = self.device()
        error = firebase_exceptions.UnavailableError("unavailable")
        for previous_attempts, delay in enumerate(list(PUSH_RETRY_DELAYS) + [None]):
            with self.subTest(attempt=previous_attempts + 1):
                Notification.objects.filter(pk=self.notification.pk).update(push_attempts=previous_attempts)
                before = timezone.now()
                result, _output = self.send_failing({device.fcm_token: error})
                self.assertEqual(result.attempts, previous_attempts + 1)
                if delay is None:
                    self.assertEqual(result.status, Notification.PushStatus.FAILED)
                    self.assertIsNone(result.next_attempt_at)
                    self.assertEqual(result.error, "UnavailableError")
                else:
                    self.assertEqual(result.status, Notification.PushStatus.PENDING)
                    self.assertGreaterEqual(result.next_attempt_at, before + delay)
                    self.assertLess(result.next_attempt_at, before + delay + timedelta(seconds=5))

    @override_settings(PUSH_MAX_ATTEMPTS=9)
    def test_last_delay_repeats_when_max_attempts_exceeds_schedule(self, _app):
        device = self.device()
        Notification.objects.filter(pk=self.notification.pk).update(push_attempts=7)
        before = timezone.now()
        result, _output = self.send_failing(
            {device.fcm_token: firebase_exceptions.UnavailableError("unavailable")}
        )
        self.assertEqual(result.status, Notification.PushStatus.PENDING)
        self.assertEqual(result.attempts, 8)
        self.assertGreaterEqual(result.next_attempt_at, before + timedelta(hours=2))
        self.assertLess(result.next_attempt_at, before + timedelta(hours=2, seconds=5))

    @patch("notifications.push_services.messaging.send_each", side_effect=RuntimeError("token-secret-value"))
    def test_send_each_failure_retries_the_whole_chunk(self, _send_each, _app):
        device = self.device()
        with self.assertLogs("notifications.push_services", level="ERROR") as logs:
            result = self.send()
        self.assertEqual(result.status, Notification.PushStatus.PENDING)
        self.assertEqual(result.error, "RuntimeError")
        self.assertEqual(result.delivered_device_ids, [])
        output = "\n".join(logs.output)
        self.assertNotIn("token-secret-value", output)
        self.assertNotIn(device.fcm_token, output)

    @patch("notifications.push_services.messaging.send_each")
    def test_initialization_failure_retries_without_sending(self, send_each, get_app):
        get_app.side_effect = RuntimeError("config")
        self.device()
        with self.assertLogs("notifications.push_services", level="ERROR"):
            result = self.send()
        self.assertEqual(result.status, Notification.PushStatus.PENDING)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.error, "RuntimeError")
        send_each.assert_not_called()

    @patch("notifications.push_services.messaging.send_each", side_effect=fake_send_each())
    def test_does_not_write_the_notification_row(self, _send_each, _app):
        self.device()
        before = Notification.objects.values().get(pk=self.notification.pk)
        self.send()
        self.assertEqual(Notification.objects.values().get(pk=self.notification.pk), before)


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
