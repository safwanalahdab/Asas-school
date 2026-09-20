from django.contrib.auth.models import AnonymousUser, Group, Permission
from django.test import TestCase

from accounts.models import User
from accounts.permission_catalog import (
    ALL_MANAGEABLE_PERMISSIONS,
    PERMISSION_CATALOG,
)
from accounts.permissions import has_direct_permission
from accounts.role_permission_templates import ROLE_PERMISSION_TEMPLATES
from accounts.services import change_user_role


def direct_permission_codes(user):
    return {
        f"{permission.content_type.app_label}.{permission.codename}"
        for permission in user.user_permissions.select_related("content_type")
    }


class PermissionCatalogTests(TestCase):
    def test_catalog_is_explicit_unique_and_deterministic(self):
        codes = [permission.code for permission in PERMISSION_CATALOG]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(set(codes), ALL_MANAGEABLE_PERMISSIONS)
        self.assertTrue(
            all(
                permission.label and permission.module
                for permission in PERMISSION_CATALOG
            )
        )
        self.assertTrue(
            all(
                permission.code.startswith(f"{permission.module}.")
                for permission in PERMISSION_CATALOG
            )
        )
        self.assertNotIn("auth.add_permission", codes)
        self.assertNotIn("contenttypes.view_contenttype", codes)
        self.assertNotIn("sessions.add_session", codes)

    def test_every_catalog_code_resolves_to_a_django_permission(self):
        django_codes = {
            f"{permission.content_type.app_label}.{permission.codename}"
            for permission in Permission.objects.select_related("content_type")
        }
        self.assertTrue(ALL_MANAGEABLE_PERMISSIONS <= django_codes)

    def test_every_template_permission_is_in_catalog(self):
        for role, permission_codes in ROLE_PERMISSION_TEMPLATES.items():
            with self.subTest(role=role):
                self.assertTrue(permission_codes <= ALL_MANAGEABLE_PERMISSIONS)

    def test_unsupported_guardian_link_change_is_not_in_catalog(self):
        self.assertNotIn(
            "students.change_guardianstudent",
            ALL_MANAGEABLE_PERMISSIONS,
        )


class RoleTemplateBusinessContractTests(TestCase):
    accountant_permissions = {
        "finance.view_gradetuitionplan",
        "finance.view_studentfinancialaccount",
        "finance.view_payment",
        "finance.add_payment",
        "finance.cancel_payment",
        "finance.view_studentdiscount",
        "finance.add_studentdiscount",
        "finance.cancel_discount",
    }
    behavior_permissions = {
        "behavior.view_behaviornote",
        "behavior.add_behaviornote",
        "behavior.change_behaviornote",
        "behavior.delete_behaviornote",
    }
    audit_log_permission = "audit_logs.view_auditlog"

    def test_supervisor_gets_behavior_crud_permissions(self):
        self.assertTrue(
            self.behavior_permissions
            <= ROLE_PERMISSION_TEMPLATES[User.Role.SUPERVISOR]
        )

    def test_secretariat_and_supervisor_can_reset_password(self):
        permission = "accounts.reset_user_password"
        self.assertIn(
            permission,
            ROLE_PERMISSION_TEMPLATES[User.Role.SECRETARIAT],
        )
        self.assertIn(
            permission,
            ROLE_PERMISSION_TEMPLATES[User.Role.SUPERVISOR],
        )

    def test_only_school_admin_gets_audit_log_permission(self):
        self.assertIn(
            self.audit_log_permission,
            ROLE_PERMISSION_TEMPLATES[User.Role.SCHOOL_ADMIN],
        )
        for role, permission_codes in ROLE_PERMISSION_TEMPLATES.items():
            if role == User.Role.SCHOOL_ADMIN:
                continue
            with self.subTest(role=role):
                self.assertNotIn(self.audit_log_permission, permission_codes)

    def test_guardian_and_tech_support_templates_remain_empty(self):
        self.assertEqual(ROLE_PERMISSION_TEMPLATES[User.Role.GUARDIAN], frozenset())
        self.assertEqual(
            ROLE_PERMISSION_TEMPLATES[User.Role.TECH_SUPPORT],
            frozenset(),
        )

    def test_teacher_gets_neither_behavior_nor_audit_log_permissions(self):
        teacher_permissions = ROLE_PERMISSION_TEMPLATES[User.Role.TEACHER]
        self.assertTrue(self.behavior_permissions.isdisjoint(teacher_permissions))
        self.assertNotIn(self.audit_log_permission, teacher_permissions)

    def test_accountant_gets_exact_finance_permissions_only(self):
        self.assertEqual(
            ROLE_PERMISSION_TEMPLATES[User.Role.ACCOUNTANT],
            frozenset(self.accountant_permissions),
        )
        self.assertNotIn(
            "finance.add_gradetuitionplan",
            ROLE_PERMISSION_TEMPLATES[User.Role.ACCOUNTANT],
        )
        self.assertNotIn(
            "finance.change_gradetuitionplan",
            ROLE_PERMISSION_TEMPLATES[User.Role.ACCOUNTANT],
        )
        self.assertFalse(
            any(
                code.startswith("accounts.")
                for code in ROLE_PERMISSION_TEMPLATES[User.Role.ACCOUNTANT]
            )
        )


class DirectPermissionTests(TestCase):
    permission_code = "students.view_student"

    def setUp(self):
        self.user = User.objects.create_user(
            username="direct-permission-user",
            role=User.Role.GUARDIAN,
        )
        self.permission = Permission.objects.get(
            content_type__app_label="students",
            codename="view_student",
        )

    def test_direct_permission_is_accepted(self):
        self.user.user_permissions.add(self.permission)
        self.assertTrue(has_direct_permission(self.user, self.permission_code))

    def test_missing_permission_is_rejected(self):
        self.assertFalse(has_direct_permission(self.user, self.permission_code))

    def test_inactive_user_is_rejected(self):
        self.user.user_permissions.add(self.permission)
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertFalse(has_direct_permission(self.user, self.permission_code))

    def test_unauthenticated_user_is_rejected(self):
        self.assertFalse(
            has_direct_permission(AnonymousUser(), self.permission_code)
        )

    def test_superuser_bypasses_direct_assignments(self):
        superuser = User.objects.create_superuser(
            username="permission-root",
            password="RootPassword!934",
        )
        self.assertTrue(has_direct_permission(superuser, self.permission_code))
        self.assertFalse(superuser.user_permissions.exists())

    def test_group_permission_is_not_a_direct_business_permission(self):
        group = Group.objects.create(name="business-group-must-not-authorize")
        group.permissions.add(self.permission)
        self.user.groups.add(group)

        self.assertTrue(self.user.has_perm(self.permission_code))
        self.assertFalse(has_direct_permission(self.user, self.permission_code))


class NewUserRoleTemplateTests(TestCase):
    def assert_role_template(self, role):
        user = User.objects.create_user(
            username=f"template-{role}",
            role=role,
        )
        self.assertEqual(
            direct_permission_codes(user),
            set(ROLE_PERMISSION_TEMPLATES[role]),
        )
        return user

    def test_teacher_gets_exact_template(self):
        self.assert_role_template(User.Role.TEACHER)

    def test_secretariat_gets_exact_template(self):
        self.assert_role_template(User.Role.SECRETARIAT)

    def test_guardian_gets_empty_template(self):
        self.assert_role_template(User.Role.GUARDIAN)

    def test_tech_support_gets_empty_template(self):
        self.assert_role_template(User.Role.TECH_SUPPORT)

    def test_accountant_gets_exact_template(self):
        self.assert_role_template(User.Role.ACCOUNTANT)

    def test_school_admin_gets_all_catalog_permissions(self):
        admin = self.assert_role_template(User.Role.SCHOOL_ADMIN)
        self.assertEqual(
            direct_permission_codes(admin),
            set(ALL_MANAGEABLE_PERMISSIONS),
        )

    def test_supervisor_gets_exact_template(self):
        self.assert_role_template(User.Role.SUPERVISOR)

    def test_explicit_role_change_replaces_business_permission_template(self):
        user = self.assert_role_template(User.Role.TEACHER)
        admin = User.objects.create_user(
            username="role-change-admin",
            role=User.Role.SCHOOL_ADMIN,
        )

        change_user_role(
            target=user,
            new_role=User.Role.SECRETARIAT,
            actor=admin,
        )
        self.assertEqual(
            direct_permission_codes(user),
            set(ROLE_PERMISSION_TEMPLATES[User.Role.SECRETARIAT]),
        )

    def test_plain_save_guardian_creation_runs_the_creation_hook(self):
        guardian = User(
            username="guardian-created-like-registration",
            role=User.Role.GUARDIAN,
        )
        guardian.save()
        self.assertEqual(
            direct_permission_codes(guardian),
            set(ROLE_PERMISSION_TEMPLATES[User.Role.GUARDIAN]),
        )

    def test_superuser_without_role_does_not_receive_a_template(self):
        superuser = User.objects.create_superuser(
            username="template-root",
            password="RootPassword!934",
        )
        self.assertEqual(superuser.role, "")
        self.assertFalse(superuser.user_permissions.exists())
