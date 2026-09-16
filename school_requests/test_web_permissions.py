from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User

from .models import SchoolRequest


class SchoolRequestBusinessPermissionTests(TestCase):
    def setUp(self):
        self.guardian = self.make_user("request-auth-guardian", User.Role.GUARDIAN)
        self.other_guardian = self.make_user("request-auth-other", User.Role.GUARDIAN)
        self.admin = self.make_user("request-auth-admin", User.Role.SCHOOL_ADMIN)
        self.tech = self.make_user("request-auth-tech", User.Role.TECH_SUPPORT)
        self.root = User.objects.create_superuser(
            username="request-auth-root", password="x", must_change_password=False
        )
        for user in (self.admin, self.tech):
            user.user_permissions.clear()
        self.request = SchoolRequest.objects.create(
            request_type=SchoolRequest.RequestType.INQUIRY,
            details="Question",
            guardian=self.guardian,
        )
        self.other_request = SchoolRequest.objects.create(
            request_type=SchoolRequest.RequestType.COMPLAINT,
            details="Other",
            guardian=self.other_guardian,
        )

    def make_user(self, username, role):
        return User.objects.create_user(
            username=username, password="x", role=role, must_change_password=False
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
                    self.client_for(user).get("/api/v1/requests/").status_code,
                    403,
                )

    def test_nontraditional_role_with_view_permission_is_allowed(self):
        self.grant(self.tech, "school_requests.view_schoolrequest")
        self.assertEqual(
            self.client_for(self.tech).get("/api/v1/requests/").status_code,
            200,
        )

    def test_view_permission_does_not_allow_answer(self):
        self.grant(self.admin, "school_requests.view_schoolrequest")
        response = self.client_for(self.admin).post(
            f"/api/v1/requests/{self.request.id}/answer/",
            {"school_response": "Answer"}, format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_reply_permission_is_independent_and_has_no_role_ceiling(self):
        self.grant(self.tech, "school_requests.reply_to_request")
        response = self.client_for(self.tech).post(
            f"/api/v1/requests/{self.request.id}/answer/",
            {"school_response": "Answer"}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.client_for(self.tech).get("/api/v1/requests/").status_code,
            403,
        )

    def test_superuser_bypass(self):
        response = self.client_for(self.root).post(
            f"/api/v1/requests/{self.request.id}/answer/",
            {"school_response": "Root answer"}, format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_web_guardian_ownership_and_create_flow_are_preserved(self):
        client = self.client_for(self.guardian)
        response = client.get("/api/v1/requests/")
        self.assertEqual(response.status_code, 200)
        payload = response.data["data"]
        rows = payload.get("results", payload) if isinstance(payload, dict) else payload
        self.assertEqual({item["id"] for item in rows}, {str(self.request.id)})
        self.assertEqual(
            client.get(f"/api/v1/requests/{self.other_request.id}/").status_code,
            404,
        )
        created = client.post(
            "/api/v1/requests/",
            {"request_type": "suggestion", "details": "Suggestion"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
