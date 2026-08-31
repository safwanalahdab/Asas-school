from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .models import AppointmentRequest


User = get_user_model()


class MobileAppointmentRequestTests(TestCase):
    list_url = "/api/v1/mobile/appointments/"

    def setUp(self):
        self.client = APIClient()
        self.guardian = self.make_user("mobile-appointment-guardian", User.Role.GUARDIAN)
        self.other_guardian = self.make_user(
            "mobile-appointment-other", User.Role.GUARDIAN
        )
        self.admin = self.make_user("mobile-appointment-admin", User.Role.SCHOOL_ADMIN)

    def make_user(self, username, role):
        return User.objects.create_user(
            username=username,
            password="StrongPass!493",
            role=role,
            must_change_password=False,
        )

    def authenticate(self, user=None, client="mobile", api_client=None):
        user = user or self.guardian
        api_client = api_client or self.client
        token = RefreshToken.for_user(user)
        token["client"] = client
        token["token_version"] = user.token_version
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    def create_appointment(self, guardian=None, **kwargs):
        return AppointmentRequest.objects.create(
            guardian=guardian or self.guardian,
            requested_date=kwargs.pop("requested_date", timezone.localdate()),
            request_reason=kwargs.pop("request_reason", "Appointment reason"),
            **kwargs,
        )

    def detail_url(self, appointment):
        return f"{self.list_url}{appointment.id}/"

    def items(self, response):
        data = response.data["data"]
        return data["results"] if isinstance(data, dict) and "results" in data else data

    def recursive_keys(self, value):
        if isinstance(value, dict):
            keys = set(value)
            for child in value.values():
                keys.update(self.recursive_keys(child))
            return keys
        if isinstance(value, list):
            keys = set()
            for child in value:
                keys.update(self.recursive_keys(child))
            return keys
        return set()

    def test_guardian_creates_pending_appointment_for_today(self):
        self.authenticate()
        response = self.client.post(
            self.list_url,
            {
                "requested_date": str(timezone.localdate()),
                "request_reason": "  Review academic progress  ",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        appointment = AppointmentRequest.objects.get(id=response.data["data"]["id"])
        self.assertEqual(appointment.guardian, self.guardian)
        self.assertEqual(appointment.status, AppointmentRequest.Status.PENDING)
        self.assertEqual(appointment.request_reason, "Review academic progress")

    def test_server_controlled_fields_cannot_be_injected(self):
        self.authenticate()
        response = self.client.post(
            self.list_url,
            {
                "requested_date": str(timezone.localdate()),
                "request_reason": "Malicious body",
                "guardian": str(self.other_guardian.id),
                "status": AppointmentRequest.Status.APPROVED,
                "decision_reason": "fake",
                "rejection_reason": "fake alias",
                "decided_by": str(self.admin.id),
                "decided_at": timezone.now().isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        appointment = AppointmentRequest.objects.get(id=response.data["data"]["id"])
        self.assertEqual(appointment.guardian, self.guardian)
        self.assertEqual(appointment.status, AppointmentRequest.Status.PENDING)
        self.assertEqual(appointment.decision_reason, "")
        self.assertIsNone(appointment.decided_by)
        self.assertIsNone(appointment.decided_at)

    def test_required_and_reason_validation(self):
        self.authenticate()
        valid_date = str(timezone.localdate())
        cases = (
            ({"request_reason": "Reason"}, "requested_date"),
            ({"requested_date": valid_date}, "request_reason"),
            ({"requested_date": valid_date, "request_reason": ""}, "request_reason"),
            ({"requested_date": valid_date, "request_reason": "   "}, "request_reason"),
        )
        for body, field in cases:
            response = self.client.post(self.list_url, body, format="json")
            self.assertEqual(response.status_code, 400)
            self.assertIn(field, response.data["errors"])

    def test_past_date_is_rejected_and_today_is_accepted(self):
        self.authenticate()
        past = timezone.localdate() - timedelta(days=1)
        rejected = self.client.post(
            self.list_url,
            {"requested_date": str(past), "request_reason": "Past"},
            format="json",
        )
        accepted = self.client.post(
            self.list_url,
            {"requested_date": str(timezone.localdate()), "request_reason": "Today"},
            format="json",
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(accepted.status_code, 201)

    def test_list_and_retrieve_are_guardian_scoped_and_paginated(self):
        own = self.create_appointment()
        other = self.create_appointment(guardian=self.other_guardian)
        self.authenticate()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("results", response.data["data"])
        returned_ids = {item["id"] for item in self.items(response)}
        self.assertIn(str(own.id), returned_ids)
        self.assertNotIn(str(other.id), returned_ids)
        self.assertEqual(self.client.get(self.detail_url(own)).status_code, 200)
        self.assertEqual(self.client.get(self.detail_url(other)).status_code, 404)

    def test_status_filters_and_invalid_status(self):
        now = timezone.now()
        pending = self.create_appointment(request_reason="Pending")
        approved = self.create_appointment(
            request_reason="Approved",
            status=AppointmentRequest.Status.APPROVED,
            decision_reason="",
            decided_by=self.admin,
            decided_at=now,
        )
        rejected = self.create_appointment(
            request_reason="Rejected",
            status=AppointmentRequest.Status.REJECTED,
            decision_reason="Unavailable",
            decided_by=self.admin,
            decided_at=now,
        )
        self.authenticate()
        for status, appointment in (
            ("pending", pending),
            ("approved", approved),
            ("rejected", rejected),
        ):
            response = self.client.get(f"{self.list_url}?status={status}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                {item["id"] for item in self.items(response)},
                {str(appointment.id)},
            )
        invalid = self.client.get(f"{self.list_url}?status=invalid")
        self.assertEqual(invalid.status_code, 400)

    def test_list_orders_newest_first(self):
        older = self.create_appointment(request_reason="Older")
        newer = self.create_appointment(request_reason="Newer")
        now = timezone.now()
        AppointmentRequest.objects.filter(pk=older.pk).update(
            created_at=now - timedelta(days=1)
        )
        AppointmentRequest.objects.filter(pk=newer.pk).update(created_at=now)
        self.authenticate()
        ids = [item["id"] for item in self.items(self.client.get(self.list_url))]
        self.assertEqual(ids[:2], [str(newer.id), str(older.id)])

    def test_authentication_web_token_and_password_gate(self):
        self.assertEqual(self.client.get(self.list_url).status_code, 401)
        self.authenticate(client="web")
        self.assertEqual(self.client.get(self.list_url).status_code, 401)
        self.guardian.must_change_password = True
        self.guardian.save(update_fields=["must_change_password"])
        self.authenticate()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "PASSWORD_CHANGE_REQUIRED")

    def test_inactive_guardian_and_non_guardian_roles_are_denied(self):
        inactive_client = APIClient()
        self.authenticate(api_client=inactive_client)
        self.guardian.is_active = False
        self.guardian.save(update_fields=["is_active"])
        self.assertEqual(inactive_client.get(self.list_url).status_code, 401)

        for role in (
            User.Role.TEACHER,
            User.Role.SCHOOL_ADMIN,
            User.Role.SUPERVISOR,
            User.Role.SECRETARIAT,
            User.Role.TECH_SUPPORT,
        ):
            user = self.make_user(f"mobile-appointment-{role}", role)
            client = APIClient()
            self.authenticate(user=user, api_client=client)
            self.assertEqual(client.get(self.list_url).status_code, 403)

    def test_mobile_response_excludes_staff_and_guardian_identity(self):
        appointment = self.create_appointment()
        self.authenticate()
        data = self.client.get(self.detail_url(appointment)).data["data"]
        forbidden = {
            "guardian",
            "guardian_username",
            "guardian_display",
            "decided_by",
            "decided_by_username",
            "decided_by_display",
            "updated_at",
        }
        self.assertTrue(forbidden.isdisjoint(self.recursive_keys(data)))

    def make_web_decision(self, appointment, action, body):
        web_client = APIClient()
        web_client.force_authenticate(user=self.admin)
        response = web_client.post(
            f"/api/v1/appointments/{appointment.id}/{action}/",
            body,
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        appointment.refresh_from_db()

    def test_web_approval_is_visible_in_mobile(self):
        appointment = self.create_appointment()
        self.make_web_decision(appointment, "approve", {})
        self.assertEqual(appointment.status, AppointmentRequest.Status.APPROVED)
        self.assertEqual(appointment.decision_reason, "")
        self.authenticate()
        data = self.client.get(self.detail_url(appointment)).data["data"]
        self.assertEqual(data["status"], "approved")
        self.assertEqual(data["rejection_reason"], "")
        self.assertIsNotNone(data["decided_at"])
        self.assertNotIn("decided_by", self.recursive_keys(data))

    def test_web_rejection_is_visible_in_mobile(self):
        appointment = self.create_appointment()
        self.make_web_decision(
            appointment,
            "reject",
            {"decision_reason": "Administration unavailable"},
        )
        self.authenticate()
        data = self.client.get(self.detail_url(appointment)).data["data"]
        self.assertEqual(data["status"], "rejected")
        self.assertEqual(data["rejection_reason"], "Administration unavailable")
        self.assertIsNotNone(data["decided_at"])
        self.assertNotIn("decided_by", self.recursive_keys(data))

    def test_mobile_is_read_only_after_create_and_has_no_decision_actions(self):
        appointment = self.create_appointment()
        self.authenticate()
        for method in ("put", "patch", "delete"):
            response = getattr(self.client, method)(
                self.detail_url(appointment), {}, format="json"
            )
            self.assertEqual(response.status_code, 405)
        for action in ("approve", "reject"):
            response = self.client.post(
                f"{self.detail_url(appointment)}{action}/", {}, format="json"
            )
            self.assertIn(response.status_code, (404, 405))
