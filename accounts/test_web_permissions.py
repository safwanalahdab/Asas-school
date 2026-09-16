from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User


class AccountsWebAuthorizationTests(TestCase):
    password = "AccountsStrong!934"
    users_url = "/api/v1/accounts/users/"

    def setUp(self):
        self.client = APIClient()
        self.admin = self.user("admin", User.Role.SCHOOL_ADMIN)
        self.secretariat = self.user("secretariat", User.Role.SECRETARIAT)
        self.supervisor = self.user("supervisor", User.Role.SUPERVISOR)
        self.teacher = self.user("teacher", User.Role.TEACHER)
        self.guardian = self.user("guardian", User.Role.GUARDIAN)
        self.support = self.user("support", User.Role.TECH_SUPPORT)
        self.root = User.objects.create_superuser(
            username="root", password=self.password,
        )

    def user(self, username, role):
        return User.objects.create_user(
            username=username,
            password=self.password,
            role=role,
            must_change_password=False,
        )

    def permission(self, code):
        app_label, codename = code.split(".", 1)
        return Permission.objects.get(
            content_type__app_label=app_label,
            codename=codename,
        )

    def grant(self, user, code):
        user.user_permissions.add(self.permission(code))

    def revoke(self, user, code):
        user.user_permissions.remove(self.permission(code))

    def authenticate(self, user):
        self.client.force_authenticate(user=user, token={"client": "web"})

    def detail_url(self, user):
        return f"{self.users_url}{user.pk}/"

    def test_view_requires_direct_permission_even_for_school_admin(self):
        self.revoke(self.admin, "accounts.view_user")
        self.authenticate(self.admin)
        self.assertEqual(self.client.get(self.users_url).status_code, 403)

    def test_view_permission_opens_endpoint_but_preserves_role_scope(self):
        self.grant(self.teacher, "accounts.view_user")
        self.authenticate(self.teacher)
        response = self.client.get(self.users_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["count"], 0)

        self.authenticate(self.supervisor)
        response = self.client.get(self.users_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["role"] for item in response.data["data"]["results"]},
            {User.Role.GUARDIAN},
        )

        self.authenticate(self.secretariat)
        response = self.client.get(self.users_url)
        usernames = {
            item["username"] for item in response.data["data"]["results"]
        }
        self.assertNotIn(self.admin.username, usernames)

    def test_superuser_bypasses_business_permissions(self):
        self.root.user_permissions.clear()
        self.authenticate(self.root)
        self.assertEqual(self.client.get(self.users_url).status_code, 200)

    def test_create_requires_add_permission_and_keeps_target_role_policy(self):
        self.revoke(self.admin, "accounts.add_user")
        self.authenticate(self.admin)
        self.assertEqual(
            self.client.post(
                self.users_url,
                {"username": "denied-create", "role": User.Role.GUARDIAN},
                format="json",
            ).status_code,
            403,
        )

        self.authenticate(self.secretariat)
        allowed = self.client.post(
            self.users_url,
            {"username": "created-guardian", "role": User.Role.GUARDIAN},
            format="json",
        )
        self.assertEqual(allowed.status_code, 201)
        denied = self.client.post(
            self.users_url,
            {"username": "denied-teacher", "role": User.Role.TEACHER},
            format="json",
        )
        self.assertEqual(denied.status_code, 400)

    def test_nontraditional_add_permission_does_not_grant_any_target_roles(self):
        self.grant(self.teacher, "accounts.add_user")
        self.authenticate(self.teacher)
        response = self.client.post(
            self.users_url,
            {"username": "teacher-created", "role": User.Role.GUARDIAN},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username="teacher-created").exists())

    def test_change_permission_is_independent_and_target_scope_is_preserved(self):
        self.revoke(self.admin, "accounts.change_user")
        self.authenticate(self.admin)
        self.assertEqual(
            self.client.patch(
                self.detail_url(self.teacher),
                {"first_name": "Denied"},
                format="json",
            ).status_code,
            403,
        )

        self.grant(self.teacher, "accounts.change_user")
        self.authenticate(self.teacher)
        self.assertEqual(
            self.client.patch(
                self.detail_url(self.guardian),
                {"first_name": "Still denied"},
                format="json",
            ).status_code,
            404,
        )

    def test_set_active_permission_is_independent_and_protections_remain(self):
        url = f"{self.detail_url(self.teacher)}set-active/"
        self.revoke(self.admin, "accounts.set_user_active")
        self.authenticate(self.admin)
        self.assertEqual(
            self.client.post(url, {"is_active": False}, format="json").status_code,
            403,
        )
        self.grant(self.admin, "accounts.set_user_active")
        self.assertEqual(
            self.client.post(
                f"{self.detail_url(self.admin)}set-active/",
                {"is_active": False},
                format="json",
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"{self.detail_url(self.root)}set-active/",
                {"is_active": False},
                format="json",
            ).status_code,
            404,
        )

    def test_reset_permission_is_independent_and_target_scope_is_preserved(self):
        self.revoke(self.admin, "accounts.reset_user_password")
        self.authenticate(self.admin)
        self.assertEqual(
            self.client.post(
                f"{self.detail_url(self.teacher)}reset-password/"
            ).status_code,
            403,
        )

        self.authenticate(self.secretariat)
        self.assertEqual(
            self.client.post(
                f"{self.detail_url(self.supervisor)}reset-password/"
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                f"{self.detail_url(self.teacher)}reset-password/"
            ).status_code,
            403,
        )

        self.grant(self.teacher, "accounts.reset_user_password")
        self.authenticate(self.teacher)
        self.assertEqual(
            self.client.post(
                f"{self.detail_url(self.guardian)}reset-password/"
            ).status_code,
            404,
        )

    def test_permission_management_keeps_school_admin_role_ceiling(self):
        catalog_url = "/api/v1/accounts/permissions/"
        for actor in (self.teacher, self.supervisor, self.secretariat, self.support):
            with self.subTest(role=actor.role):
                self.grant(actor, "accounts.manage_user_permissions")
                self.authenticate(actor)
                self.assertEqual(self.client.get(catalog_url).status_code, 403)

        self.authenticate(self.admin)
        self.assertEqual(self.client.get(catalog_url).status_code, 200)
        self.authenticate(self.root)
        self.assertEqual(self.client.get(catalog_url).status_code, 200)
