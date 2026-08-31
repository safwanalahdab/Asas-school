from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import AppointmentRequest


User = get_user_model()


class AppointmentWebTests(TestCase):
    list_url = "/api/v1/appointments/"

    def setUp(self):
        self.guardian = self.user("appt-guardian", User.Role.GUARDIAN)
        self.admin = self.user("appt-admin", User.Role.SCHOOL_ADMIN)
        self.secretariat = self.user("appt-secretariat", User.Role.SECRETARIAT)
        self.supervisor = self.user("appt-supervisor", User.Role.SUPERVISOR)
        self.teacher = self.user("appt-teacher", User.Role.TEACHER)
        self.tech = self.user("appt-tech", User.Role.TECH_SUPPORT)
        self.root = User.objects.create_superuser(
            username="appt-root", password="StrongPass!493"
        )

    def user(self, username, role):
        return User.objects.create_user(
            username=username, password="StrongPass!493", role=role,
            must_change_password=False,
        )

    def appointment(self):
        return AppointmentRequest.objects.create(
            guardian=self.guardian, requested_date=timezone.localdate(),
            request_reason="Appointment reason",
        )

    def api_client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def detail(self, obj):
        return f"{self.list_url}{obj.id}/"

    def action(self, obj, name):
        return f"{self.detail(obj)}{name}/"

    def test_admin_list_retrieve_and_approve_without_reason(self):
        obj = self.appointment()
        client = self.api_client(self.admin)
        self.assertEqual(client.get(self.list_url).status_code, 200)
        self.assertEqual(client.get(self.detail(obj)).status_code, 200)
        self.assertEqual(client.post(self.action(obj, "approve"), {}, format="json").status_code, 200)
        obj.refresh_from_db()
        self.assertEqual(obj.status, AppointmentRequest.Status.APPROVED)
        self.assertEqual(obj.decision_reason, "")
        self.assertEqual(obj.decided_by, self.admin)
        self.assertIsNotNone(obj.decided_at)

    def test_admin_reject_validation_and_result(self):
        client = self.api_client(self.admin)
        for body in ({}, {"decision_reason": ""}, {"decision_reason": "   "}):
            obj = self.appointment()
            self.assertEqual(client.post(self.action(obj, "reject"), body, format="json").status_code, 400)
            obj.refresh_from_db()
            self.assertEqual(obj.status, AppointmentRequest.Status.PENDING)
        obj = self.appointment()
        response = client.post(
            self.action(obj, "reject"),
            {"decision_reason": "  Administration unavailable  "}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        obj.refresh_from_db()
        self.assertEqual(obj.status, AppointmentRequest.Status.REJECTED)
        self.assertEqual(obj.decision_reason, "Administration unavailable")
        self.assertEqual(obj.decided_by, self.admin)
        self.assertIsNotNone(obj.decided_at)

    def test_final_decisions_cannot_change_or_repeat(self):
        client = self.api_client(self.admin)
        approved, rejected = self.appointment(), self.appointment()
        client.post(self.action(approved, "approve"), {}, format="json")
        client.post(self.action(rejected, "reject"), {"decision_reason": "No"}, format="json")
        for obj, name, body in (
            (approved, "approve", {}),
            (approved, "reject", {"decision_reason": "Change"}),
            (rejected, "approve", {}),
            (rejected, "reject", {"decision_reason": "Repeat"}),
        ):
            self.assertEqual(client.post(self.action(obj, name), body, format="json").status_code, 400)

    def test_secretariat_is_read_only(self):
        obj = self.appointment()
        client = self.api_client(self.secretariat)
        self.assertEqual(client.get(self.list_url).status_code, 200)
        self.assertEqual(client.get(self.detail(obj)).status_code, 200)
        self.assertEqual(client.post(self.action(obj, "approve"), {}, format="json").status_code, 403)
        self.assertEqual(client.post(self.action(obj, "reject"), {"decision_reason": "No"}, format="json").status_code, 403)
        self.assertEqual(client.post(self.list_url, {"requested_date": str(timezone.localdate()), "request_reason": "No"}, format="json").status_code, 403)

    def test_guardian_and_disallowed_staff_have_no_web_access(self):
        obj = self.appointment()
        for user in (self.guardian, self.supervisor, self.teacher, self.tech):
            client = self.api_client(user)
            self.assertEqual(client.get(self.list_url).status_code, 403)
            self.assertEqual(client.get(self.detail(obj)).status_code, 403)
            self.assertEqual(client.post(self.list_url, {"requested_date": str(timezone.localdate()), "request_reason": "No"}, format="json").status_code, 403)

    def test_superuser_can_list_retrieve_approve_and_reject(self):
        approved, rejected = self.appointment(), self.appointment()
        client = self.api_client(self.root)
        self.assertEqual(client.get(self.list_url).status_code, 200)
        self.assertEqual(client.get(self.detail(approved)).status_code, 200)
        self.assertEqual(client.post(self.action(approved, "approve"), {}, format="json").status_code, 200)
        self.assertEqual(client.post(self.action(rejected, "reject"), {"decision_reason": "No"}, format="json").status_code, 200)


class AppointmentConstraintTests(TestCase):
    def setUp(self):
        self.guardian = User.objects.create_user(
            username="constraint-guardian", password="StrongPass!493",
            role=User.Role.GUARDIAN, must_change_password=False,
        )
        self.admin = User.objects.create_user(
            username="constraint-admin", password="StrongPass!493",
            role=User.Role.SCHOOL_ADMIN, must_change_password=False,
        )

    def create(self, **kwargs):
        return AppointmentRequest.objects.create(
            guardian=self.guardian, requested_date=timezone.localdate(),
            request_reason="Constraint test", **kwargs,
        )

    def test_valid_constraint_states(self):
        now = timezone.now()
        self.create()
        self.create(status="approved", decision_reason="", decided_by=self.admin, decided_at=now)
        self.create(status="rejected", decision_reason="Reason", decided_by=self.admin, decided_at=now)
        self.assertEqual(AppointmentRequest.objects.count(), 3)

    def test_invalid_constraint_states(self):
        now = timezone.now()
        invalid = (
            {"status": "pending", "decision_reason": "Unexpected"},
            {"status": "approved", "decision_reason": "Fake", "decided_by": self.admin, "decided_at": now},
            {"status": "approved", "decision_reason": ""},
            {"status": "rejected", "decision_reason": "", "decided_by": self.admin, "decided_at": now},
            {"status": "rejected", "decision_reason": "Reason"},
        )
        for state in invalid:
            with self.assertRaises(IntegrityError), transaction.atomic():
                self.create(**state)
