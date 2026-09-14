from uuid import uuid4

from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from accounts.permission_catalog import (
    ALL_MANAGEABLE_PERMISSIONS,
    MODULE_LABELS,
    PERMISSION_CATALOG,
    direct_business_permission_codes,
)
from audit_logs.models import AuditLog


MANAGE_PERMISSIONS = "accounts.manage_user_permissions"


def permission_for(code):
    app_label, codename = code.split(".", 1)
    return Permission.objects.get(
        content_type__app_label=app_label,
        codename=codename,
    )


class PermissionApiTestCase(TestCase):
    password = "PermissionStrong!934"

    def setUp(self):
        self.client = APIClient()

    def create_user(self, username, role, **kwargs):
        return User.objects.create_user(
            username=username,
            password=self.password,
            role=role,
            must_change_password=False,
            **kwargs,
        )

    def authenticate(self, user):
        self.client.force_authenticate(user, token={"client": "web"})

    def catalog_url(self):
        return "/api/v1/accounts/permissions/"

    def user_permissions_url(self, user):
        return f"/api/v1/accounts/users/{user.pk}/permissions/"


class PermissionManagementAccessTests(PermissionApiTestCase):
    def test_superuser_can_get_catalog(self):
        root = User.objects.create_superuser(
            username="catalog-root",
            password=self.password,
        )
        self.authenticate(root)
        self.assertEqual(self.client.get(self.catalog_url()).status_code, 200)

    def test_school_admin_requires_direct_management_permission(self):
        admin = self.create_user("catalog-admin", User.Role.SCHOOL_ADMIN)
        self.authenticate(admin)
        self.assertEqual(self.client.get(self.catalog_url()).status_code, 200)

        admin.user_permissions.remove(permission_for(MANAGE_PERMISSIONS))
        self.assertEqual(self.client.get(self.catalog_url()).status_code, 403)

    def test_other_roles_are_denied_even_with_direct_permission(self):
        for role in (
            User.Role.TEACHER,
            User.Role.SUPERVISOR,
            User.Role.TECH_SUPPORT,
            User.Role.SECRETARIAT,
        ):
            with self.subTest(role=role):
                user = self.create_user(f"catalog-{role}", role)
                user.user_permissions.add(permission_for(MANAGE_PERMISSIONS))
                self.authenticate(user)
                self.assertEqual(self.client.get(self.catalog_url()).status_code, 403)

    def test_inactive_school_admin_is_denied(self):
        admin = self.create_user(
            "inactive-catalog-admin",
            User.Role.SCHOOL_ADMIN,
            is_active=False,
        )
        self.authenticate(admin)
        self.assertEqual(self.client.get(self.catalog_url()).status_code, 403)


class PermissionCatalogApiTests(PermissionApiTestCase):
    def setUp(self):
        super().setUp()
        self.root = User.objects.create_superuser(
            username="catalog-shape-root",
            password=self.password,
        )
        self.authenticate(self.root)

    def test_catalog_contains_only_business_permissions_with_module_labels(self):
        response = self.client.get(self.catalog_url())
        self.assertEqual(response.status_code, 200)
        modules = response.data["data"]["modules"]
        returned_codes = [
            permission["code"]
            for module in modules
            for permission in module["permissions"]
        ]
        self.assertEqual(set(returned_codes), set(ALL_MANAGEABLE_PERMISSIONS))
        self.assertNotIn("auth.add_group", returned_codes)
        self.assertTrue(all(module["label"] for module in modules))
        self.assertEqual(
            [module["module"] for module in modules],
            [
                module
                for module in MODULE_LABELS
                if any(item.module == module for item in PERMISSION_CATALOG)
            ],
        )

    def test_permission_order_inside_modules_follows_catalog(self):
        response = self.client.get(self.catalog_url())
        for module in response.data["data"]["modules"]:
            expected = [
                permission.code
                for permission in PERMISSION_CATALOG
                if permission.module == module["module"]
            ]
            self.assertEqual(
                [permission["code"] for permission in module["permissions"]],
                expected,
            )


class UserPermissionsApiTests(PermissionApiTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.create_user("permission-admin", User.Role.SCHOOL_ADMIN)
        self.target = self.create_user("permission-target", User.Role.GUARDIAN)
        self.authenticate(self.admin)

    def test_get_returns_direct_catalog_permissions_only_in_catalog_order(self):
        first = "students.view_student"
        second = "finance.add_payment"
        internal = permission_for("auth.add_group")
        group_only = permission_for("homework.add_homework")
        self.target.user_permissions.add(permission_for(first), permission_for(second), internal)
        group = Group.objects.create(name="permission-api-group")
        group.permissions.add(group_only)
        self.target.groups.add(group)

        response = self.client.get(self.user_permissions_url(self.target))
        self.assertEqual(response.status_code, 200)
        expected = [
            item.code
            for item in PERMISSION_CATALOG
            if item.code in {first, second}
        ]
        self.assertEqual(response.data["data"]["permissions"], expected)
        self.assertEqual(response.data["data"]["user"]["username"], self.target.username)

    def test_put_fully_replaces_business_permissions(self):
        initial = [
            "students.view_student",
            "homework.add_homework",
            "finance.add_payment",
        ]
        self.target.user_permissions.set(permission_for(code) for code in initial)
        expanded = ["announcements.view_announcement", *initial]

        response = self.client.put(
            self.user_permissions_url(self.target),
            {"permissions": expanded},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(direct_business_permission_codes(self.target)), set(expanded))

        only = ["announcements.view_announcement"]
        response = self.client.put(
            self.user_permissions_url(self.target),
            {"permissions": only},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(direct_business_permission_codes(self.target), only)

    def test_put_nonexistent_target_returns_404_without_side_effects(self):
        admin_permissions = direct_business_permission_codes(self.admin)
        target_permissions = direct_business_permission_codes(self.target)
        user_count = User.objects.count()
        audit_count = AuditLog.objects.count()

        response = self.client.put(
            f"/api/v1/accounts/users/{uuid4()}/permissions/",
            {"permissions": ["students.view_student"]},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["code"], "USER_NOT_FOUND")
        self.assertEqual(response.data["message"], "المستخدم المطلوب غير موجود.")
        self.assertEqual(User.objects.count(), user_count)
        self.assertEqual(AuditLog.objects.count(), audit_count)
        self.assertEqual(
            direct_business_permission_codes(self.admin), admin_permissions
        )
        self.assertEqual(
            direct_business_permission_codes(self.target), target_permissions
        )

    def test_put_preserves_unmanaged_direct_django_permissions(self):
        internal = permission_for("auth.add_group")
        self.target.user_permissions.add(internal)
        self.client.put(
            self.user_permissions_url(self.target),
            {"permissions": ["students.view_student"]},
            format="json",
        )
        self.assertTrue(self.target.user_permissions.filter(pk=internal.pk).exists())

    def test_invalid_internal_duplicate_and_non_string_codes_do_not_mutate(self):
        original = ["students.view_student"]
        self.target.user_permissions.set(permission_for(code) for code in original)
        invalid_payloads = (
            {"permissions": ["not.a.permission"]},
            {"permissions": ["auth.add_group"]},
            {"permissions": [original[0], original[0]]},
            {"permissions": [123]},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.put(
                    self.user_permissions_url(self.target),
                    payload,
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(direct_business_permission_codes(self.target), original)

    def test_school_admin_and_superuser_cannot_edit_themselves(self):
        self.assertEqual(
            self.client.put(
                self.user_permissions_url(self.admin),
                {"permissions": []},
                format="json",
            ).status_code,
            403,
        )
        root = User.objects.create_superuser(
            username="self-edit-root",
            password=self.password,
        )
        self.authenticate(root)
        self.assertEqual(
            self.client.put(
                self.user_permissions_url(root),
                {"permissions": []},
                format="json",
            ).status_code,
            403,
        )

    def test_superuser_target_get_and_put_are_denied(self):
        root = User.objects.create_superuser(
            username="target-root",
            password=self.password,
        )
        self.assertEqual(self.client.get(self.user_permissions_url(root)).status_code, 403)
        self.assertEqual(
            self.client.put(
                self.user_permissions_url(root),
                {"permissions": []},
                format="json",
            ).status_code,
            403,
        )


class LastPermissionManagerTests(PermissionApiTestCase):
    def setUp(self):
        super().setUp()
        self.root = User.objects.create_superuser(
            username="manager-protection-root",
            password=self.password,
        )
        self.target = self.create_user("only-manager", User.Role.SCHOOL_ADMIN)
        self.authenticate(self.root)

    def remove_management_permission(self):
        remaining = [
            code
            for code in direct_business_permission_codes(self.target)
            if code != MANAGE_PERMISSIONS
        ]
        return self.client.put(
            self.user_permissions_url(self.target),
            {"permissions": remaining},
            format="json",
        )

    def test_last_active_direct_holder_is_protected(self):
        response = self.remove_management_permission()
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            self.target.user_permissions.filter(pk=permission_for(MANAGE_PERMISSIONS).pk).exists()
        )

    def test_removal_is_allowed_when_another_active_direct_holder_exists(self):
        self.create_user("second-manager", User.Role.SCHOOL_ADMIN)
        self.assertEqual(self.remove_management_permission().status_code, 200)

    def test_inactive_non_direct_and_group_holders_do_not_count(self):
        inactive = self.create_user(
            "inactive-manager",
            User.Role.SCHOOL_ADMIN,
            is_active=False,
        )
        non_direct = self.create_user("non-direct-manager", User.Role.SCHOOL_ADMIN)
        non_direct.user_permissions.remove(permission_for(MANAGE_PERMISSIONS))
        group = Group.objects.create(name="manager-group")
        group.permissions.add(permission_for(MANAGE_PERMISSIONS))
        non_direct.groups.add(group)
        self.assertTrue(inactive.user_permissions.filter(pk=permission_for(MANAGE_PERMISSIONS).pk))
        self.assertEqual(self.remove_management_permission().status_code, 403)


class PermissionManagementAuditTests(PermissionApiTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.create_user("audit-permission-admin", User.Role.SCHOOL_ADMIN)
        self.target = self.create_user("audit-permission-target", User.Role.GUARDIAN)
        self.authenticate(self.admin)

    def test_successful_change_records_deterministic_audit_metadata(self):
        before = ["students.view_student"]
        after = ["homework.add_homework", "finance.add_payment"]
        self.target.user_permissions.set(permission_for(code) for code in before)
        response = self.client.put(
            self.user_permissions_url(self.target),
            {"permissions": after},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        event = AuditLog.objects.get(
            target_id=str(self.target.pk),
            action=AuditLog.Action.UPDATE,
        )
        self.assertEqual(event.metadata["before_permissions"], before)
        self.assertEqual(
            event.metadata["after_permissions"],
            direct_business_permission_codes(self.target),
        )
        self.assertEqual(event.metadata["added_permissions"], sorted(after))
        self.assertEqual(event.metadata["removed_permissions"], before)

    def test_failed_and_unchanged_puts_do_not_create_audit_events(self):
        current = ["students.view_student"]
        self.target.user_permissions.set(permission_for(code) for code in current)
        invalid = self.client.put(
            self.user_permissions_url(self.target),
            {"permissions": ["auth.add_group"]},
            format="json",
        )
        unchanged = self.client.put(
            self.user_permissions_url(self.target),
            {"permissions": current},
            format="json",
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(unchanged.status_code, 200)
        self.assertFalse(
            AuditLog.objects.filter(
                target_id=str(self.target.pk),
                action=AuditLog.Action.UPDATE,
            ).exists()
        )


class WebMePermissionTests(PermissionApiTestCase):
    url = "/api/v1/auth/web/me/"

    def test_normal_user_gets_direct_catalog_permissions_only(self):
        user = self.create_user("me-permission-user", User.Role.TEACHER)
        user.user_permissions.clear()
        direct = permission_for("students.view_student")
        internal = permission_for("auth.add_group")
        group_permission = permission_for("homework.add_homework")
        user.user_permissions.add(direct, internal)
        group = Group.objects.create(name="me-permission-group")
        group.permissions.add(group_permission)
        user.groups.add(group)
        self.authenticate(user)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["permissions"], ["students.view_student"])

    def test_superuser_gets_all_catalog_permissions(self):
        root = User.objects.create_superuser(
            username="me-permission-root",
            password=self.password,
        )
        self.authenticate(root)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["data"]["permissions"],
            [permission.code for permission in PERMISSION_CATALOG],
        )

    def test_login_response_does_not_gain_permissions(self):
        user = self.create_user("login-contract-user", User.Role.SCHOOL_ADMIN)
        self.client.force_authenticate(user=None)
        response = self.client.post(
            "/api/v1/auth/web/login/",
            {"identifier": user.username, "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("permissions", response.data["data"]["user"])
