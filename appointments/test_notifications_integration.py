from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from notifications.models import Notification
from notifications.push_services import build_notification_message

from .models import AppointmentRequest
from .services import (
    APPOINTMENT_APPROVED_BODY,
    APPOINTMENT_NOTIFICATION_TITLE,
    APPOINTMENT_REJECTED_BODY,
    approve_appointment_request,
    reject_appointment_request,
)


User = get_user_model()


class AppointmentNotificationIntegrationTests(TestCase):
    inbox_url = "/api/v1/mobile/notifications/"

    def setUp(self):
        self.guardian = self.make_user(
            "appointment-notification-guardian", User.Role.GUARDIAN
        )
        self.other_guardian = self.make_user(
            "appointment-notification-other", User.Role.GUARDIAN
        )
        self.admin = self.make_user(
            "appointment-notification-admin", User.Role.SCHOOL_ADMIN
        )

    def make_user(self, username, role):
        return User.objects.create_user(
            username=username,
            password="StrongPass!493",
            role=role,
            must_change_password=False,
        )

    def appointment(self, guardian=None):
        return AppointmentRequest.objects.create(
            guardian=guardian or self.guardian,
            requested_date=timezone.localdate(),
            request_reason="Appointment reason",
        )

    def authenticate_mobile(self, user):
        token = RefreshToken.for_user(user)
        token["client"] = "mobile"
        token["token_version"] = user.token_version
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        return client

    def test_approve_creates_expected_guardian_notification(self):
        appointment = self.appointment()
        result = approve_appointment_request(
            appointment=appointment,
            actor=self.admin,
        )
        notification = Notification.objects.get()

        self.assertEqual(result.status, AppointmentRequest.Status.APPROVED)
        self.assertEqual(notification.recipient, appointment.guardian)
        self.assertEqual(
            notification.notification_type,
            Notification.NotificationType.APPOINTMENT,
        )
        self.assertIsNone(notification.student)
        self.assertEqual(notification.resource_type, "appointment")
        self.assertEqual(notification.resource_id, appointment.id)
        self.assertEqual(
            notification.event_key,
            f"appointment:{appointment.id}:approved",
        )
        self.assertEqual(notification.title, APPOINTMENT_NOTIFICATION_TITLE)
        self.assertEqual(notification.body, APPOINTMENT_APPROVED_BODY)

    def test_reject_creates_private_mobile_safe_notification(self):
        appointment = self.appointment()
        private_reason = "Sensitive internal rejection details"
        result = reject_appointment_request(
            appointment=appointment,
            actor=self.admin,
            decision_reason=private_reason,
        )
        notification = Notification.objects.get()

        self.assertEqual(result.status, AppointmentRequest.Status.REJECTED)
        self.assertEqual(notification.recipient, appointment.guardian)
        self.assertEqual(notification.resource_type, "appointment")
        self.assertEqual(notification.resource_id, appointment.id)
        self.assertEqual(
            notification.event_key,
            f"appointment:{appointment.id}:rejected",
        )
        self.assertEqual(notification.title, APPOINTMENT_NOTIFICATION_TITLE)
        self.assertEqual(notification.body, APPOINTMENT_REJECTED_BODY)
        self.assertNotIn(private_reason, notification.body)

    def test_final_state_attempts_do_not_create_extra_notifications(self):
        approved = self.appointment()
        rejected = self.appointment()
        approve_appointment_request(appointment=approved, actor=self.admin)
        reject_appointment_request(
            appointment=rejected,
            actor=self.admin,
            decision_reason="No availability",
        )

        cases = (
            (approve_appointment_request, approved, {}),
            (reject_appointment_request, approved, {"decision_reason": "Change"}),
            (approve_appointment_request, rejected, {}),
            (reject_appointment_request, rejected, {"decision_reason": "Repeat"}),
        )
        for service, appointment, extra in cases:
            with self.subTest(service=service.__name__, status=appointment.status):
                with self.assertRaises(ValidationError):
                    service(appointment=appointment, actor=self.admin, **extra)
        self.assertEqual(Notification.objects.count(), 2)

    def test_notification_is_visible_only_in_recipient_mobile_inbox(self):
        appointment = self.appointment()
        approve_appointment_request(appointment=appointment, actor=self.admin)

        recipient_response = self.authenticate_mobile(self.guardian).get(
            self.inbox_url
        )
        other_response = self.authenticate_mobile(self.other_guardian).get(
            self.inbox_url
        )
        recipient_ids = {
            item["id"] for item in recipient_response.data["data"]["results"]
        }
        other_ids = {
            item["id"] for item in other_response.data["data"]["results"]
        }
        notification_id = str(Notification.objects.get().id)

        self.assertEqual(recipient_response.status_code, 200)
        self.assertEqual(other_response.status_code, 200)
        self.assertIn(notification_id, recipient_ids)
        self.assertNotIn(notification_id, other_ids)

    def test_notification_failure_rolls_back_approve_decision(self):
        appointment = self.appointment()
        with patch(
            "appointments.services.create_notification",
            side_effect=DjangoValidationError("Notification failure"),
        ):
            with self.assertRaises(DjangoValidationError):
                approve_appointment_request(
                    appointment=appointment,
                    actor=self.admin,
                )

        appointment.refresh_from_db()
        self.assertEqual(appointment.status, AppointmentRequest.Status.PENDING)
        self.assertEqual(appointment.decision_reason, "")
        self.assertIsNone(appointment.decided_by)
        self.assertIsNone(appointment.decided_at)
        self.assertEqual(Notification.objects.count(), 0)

    def test_notification_failure_rolls_back_reject_decision(self):
        appointment = self.appointment()
        with patch(
            "appointments.services.create_notification",
            side_effect=DjangoValidationError("Notification failure"),
        ):
            with self.assertRaises(DjangoValidationError):
                reject_appointment_request(
                    appointment=appointment,
                    actor=self.admin,
                    decision_reason="No availability",
                )

        appointment.refresh_from_db()
        self.assertEqual(appointment.status, AppointmentRequest.Status.PENDING)
        self.assertEqual(appointment.decision_reason, "")
        self.assertIsNone(appointment.decided_by)
        self.assertIsNone(appointment.decided_at)
        self.assertEqual(Notification.objects.count(), 0)

    @override_settings(FIREBASE_PUSH_ENABLED=True)
    @patch("notifications.push_services.safe_send_notification_push")
    def test_approve_and_reject_schedule_push_only_after_commit(self, safe_send):
        approved = self.appointment()
        rejected = self.appointment()
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            approve_appointment_request(appointment=approved, actor=self.admin)
            reject_appointment_request(
                appointment=rejected,
                actor=self.admin,
                decision_reason="Private decision reason",
            )
            safe_send.assert_not_called()

        self.assertEqual(len(callbacks), 2)
        self.assertEqual(safe_send.call_count, 2)
        notification_ids = set(
            Notification.objects.filter(
                resource_id__in=[approved.id, rejected.id]
            ).values_list("id", flat=True)
        )
        self.assertEqual(
            {call.args[0] for call in safe_send.call_args_list},
            notification_ids,
        )
        rejected_notification = Notification.objects.get(resource_id=rejected.id)
        message = build_notification_message(
            notification=rejected_notification,
            token="test-token",
        )
        self.assertNotIn("decision_reason", message.data)
        self.assertNotIn("Private decision reason", message.notification.body)

    @override_settings(FIREBASE_PUSH_ENABLED=True)
    @patch("notifications.push_services.safe_send_notification_push")
    def test_invalid_final_state_does_not_schedule_new_push(self, safe_send):
        appointment = self.appointment()
        with self.captureOnCommitCallbacks(execute=True):
            approve_appointment_request(appointment=appointment, actor=self.admin)
        safe_send.reset_mock()

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(ValidationError):
                approve_appointment_request(appointment=appointment, actor=self.admin)
        self.assertEqual(callbacks, [])
        safe_send.assert_not_called()
