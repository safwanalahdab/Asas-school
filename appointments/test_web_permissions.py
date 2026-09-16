from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User

from .models import AppointmentRequest


class AppointmentBusinessPermissionTests(TestCase):
    def setUp(self):
        self.guardian = self.make_user("appointment-auth-guardian", User.Role.GUARDIAN)
        self.admin = self.make_user("appointment-auth-admin", User.Role.SCHOOL_ADMIN)
        self.tech = self.make_user("appointment-auth-tech", User.Role.TECH_SUPPORT)
        self.root = User.objects.create_superuser(
            username="appointment-auth-root", password="x", must_change_password=False
        )
        for user in (self.admin, self.tech):
            user.user_permissions.clear()
        self.appointment = self.make_appointment()

    def make_user(self, username, role):
        return User.objects.create_user(
            username=username, password="x", role=role, must_change_password=False
        )

    def make_appointment(self):
        return AppointmentRequest.objects.create(
            guardian=self.guardian,
            requested_date=timezone.localdate(),
            request_reason="Meeting",
        )

    def grant(self, user, code):
        app_label, codename = code.split(".", 1)
        user.user_permissions.add(Permission.objects.get(
            content_type__app_label=app_label, codename=codename
        ))

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_user_and_school_admin_without_view_permission_are_forbidden(self):
        for user in (self.admin, self.tech):
            with self.subTest(role=user.role):
                self.assertEqual(
                    self.client_for(user).get("/api/v1/appointments/").status_code,
                    403,
                )

    def test_nontraditional_role_with_view_permission_is_allowed(self):
        self.grant(self.tech, "appointments.view_appointmentrequest")
        self.assertEqual(
            self.client_for(self.tech).get("/api/v1/appointments/").status_code,
            200,
        )

    def test_view_permission_does_not_allow_decision(self):
        self.grant(self.admin, "appointments.view_appointmentrequest")
        self.assertEqual(
            self.client_for(self.admin).post(
                f"/api/v1/appointments/{self.appointment.id}/approve/",
                {}, format="json",
            ).status_code,
            403,
        )

    def test_decide_permission_is_independent_and_has_no_role_ceiling(self):
        self.grant(self.tech, "appointments.decide_appointment_request")
        response = self.client_for(self.tech).post(
            f"/api/v1/appointments/{self.appointment.id}/approve/",
            {}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.client_for(self.tech).get("/api/v1/appointments/").status_code,
            403,
        )

    def test_reject_uses_decide_permission(self):
        appointment = self.make_appointment()
        self.grant(self.tech, "appointments.decide_appointment_request")
        response = self.client_for(self.tech).post(
            f"/api/v1/appointments/{appointment.id}/reject/",
            {"decision_reason": "Unavailable"}, format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_superuser_bypass(self):
        self.assertEqual(
            self.client_for(self.root).get("/api/v1/appointments/").status_code,
            200,
        )
        self.assertEqual(
            self.client_for(self.root).post(
                f"/api/v1/appointments/{self.appointment.id}/approve/",
                {}, format="json",
            ).status_code,
            200,
        )
