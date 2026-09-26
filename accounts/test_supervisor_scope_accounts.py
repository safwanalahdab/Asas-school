from unittest.mock import patch
from datetime import timedelta

from django.contrib.auth.models import Permission
from django.contrib.admin.sites import AdminSite
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from academics.models import (
    AcademicYear,
    GradeLevel,
    GradeSubject,
    Section,
    Subject,
    SupervisorScope,
)
from academics.supervisor_scope_services import set_supervisor_scope
from accounts.models import User
from accounts.admin import CustomUserAdmin
from accounts.permission_catalog import direct_business_permission_codes
from accounts.role_permission_templates import ROLE_PERMISSION_TEMPLATES
from accounts.serializers import WebTokenRefreshSerializer
from accounts.services import change_user_role
from teaching.models import TeacherAssignment


class SupervisorScopeAccountsTests(TestCase):
    password = "ScopeStrong!934"
    users_url = "/api/v1/accounts/users/"

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="scope-accounts-admin",
            password=self.password,
            role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
        )
        self.secretariat = User.objects.create_user(
            username="scope-accounts-secretariat",
            password=self.password,
            role=User.Role.SECRETARIAT,
            must_change_password=False,
        )
        self.client.force_authenticate(self.admin, token={"client": "web"})

    def create_supervisor(self, username="api-supervisor", scope=None):
        return self.client.post(
            self.users_url,
            {
                "username": username,
                "role": User.Role.SUPERVISOR,
                "supervisor_scope": scope or {"scope_type": "all", "stages": []},
            },
            format="json",
        )

    def test_create_supervisor_with_all_and_selected_stages(self):
        response = self.create_supervisor()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.data["data"]["supervisor_scope"],
            {
                "scope_type": "all",
                "scope_type_display": "كل المراحل",
                "stages": [],
                "stages_display": [],
            },
        )

        selected = self.create_supervisor(
            username="selected-supervisor",
            scope={
                "scope_type": "selected_stages",
                "stages": ["primary", "preparatory"],
            },
        )
        self.assertEqual(selected.status_code, 201)
        self.assertEqual(
            selected.data["data"]["supervisor_scope"]["stages"],
            ["primary", "preparatory"],
        )

    def test_create_supervisor_requires_explicit_valid_scope(self):
        missing = self.client.post(
            self.users_url,
            {"username": "missing-scope", "role": User.Role.SUPERVISOR},
            format="json",
        )
        self.assertEqual(missing.status_code, 400)
        self.assertFalse(User.objects.filter(username="missing-scope").exists())

        invalid = self.create_supervisor(
            username="invalid-scope",
            scope={"scope_type": "selected_stages", "stages": []},
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertFalse(User.objects.filter(username="invalid-scope").exists())

    def test_admin_updates_scope_and_responses_are_consistent(self):
        created = self.create_supervisor()
        user = User.objects.get(pk=created.data["data"]["id"])
        detail_url = f"{self.users_url}{user.pk}/"
        updated = self.client.patch(
            detail_url,
            {
                "supervisor_scope": {
                    "scope_type": "selected_stages",
                    "stages": ["primary"],
                }
            },
            format="json",
        )
        self.assertEqual(updated.status_code, 200)
        expected = {
            "scope_type": "selected_stages",
            "scope_type_display": "مراحل محددة",
            "stages": ["primary"],
            "stages_display": ["الابتدائية"],
        }
        self.assertEqual(updated.data["data"]["supervisor_scope"], expected)
        retrieved = self.client.get(detail_url)
        self.assertEqual(retrieved.data["data"]["supervisor_scope"], expected)

        self.client.force_authenticate(user, token={"client": "web"})
        me = self.client.get("/api/v1/auth/web/me/")
        self.assertEqual(me.data["data"]["supervisor_scope"], expected)

    def test_non_admin_cannot_update_role_or_scope_even_to_current_values(self):
        created = self.create_supervisor()
        user = User.objects.get(pk=created.data["data"]["id"])
        self.client.force_authenticate(self.secretariat, token={"client": "web"})
        url = f"{self.users_url}{user.pk}/"
        self.assertEqual(
            self.client.patch(url, {"role": User.Role.SUPERVISOR}, format="json").status_code,
            404,
        )
        self.assertEqual(
            self.client.patch(
                url,
                {"supervisor_scope": {"scope_type": "all", "stages": []}},
                format="json",
            ).status_code,
            404,
        )

    def test_non_supervisor_roles_return_null_scope_and_reject_extra_scope(self):
        accountant = User.objects.create_user(
            username="scope-accountant",
            role=User.Role.ACCOUNTANT,
        )
        response = self.client.get(f"{self.users_url}{accountant.pk}/")
        self.assertIsNone(response.data["data"]["supervisor_scope"])
        rejected = self.client.patch(
            f"{self.users_url}{accountant.pk}/",
            {"supervisor_scope": {"scope_type": "all", "stages": []}},
            format="json",
        )
        self.assertEqual(rejected.status_code, 400)

    def test_teacher_to_accountant_replaces_business_permissions_and_invalidates_token(self):
        teacher = User.objects.create_user(
            username="role-teacher-accountant",
            role=User.Role.TEACHER,
        )
        unmanaged = Permission.objects.get(
            content_type__app_label="auth",
            codename="view_permission",
        )
        teacher.user_permissions.add(unmanaged)
        refresh = RefreshToken.for_user(teacher)
        refresh["client"] = "web"
        refresh["token_version"] = teacher.token_version

        response = self.client.patch(
            f"{self.users_url}{teacher.pk}/",
            {"role": User.Role.ACCOUNTANT},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        teacher.refresh_from_db()
        self.assertEqual(
            set(direct_business_permission_codes(teacher)),
            set(ROLE_PERMISSION_TEMPLATES[User.Role.ACCOUNTANT]),
        )
        self.assertTrue(teacher.user_permissions.filter(pk=unmanaged.pk).exists())
        self.assertEqual(teacher.token_version, 2)
        with self.assertRaises(AuthenticationFailed):
            WebTokenRefreshSerializer(data={"refresh": str(refresh)}).is_valid(
                raise_exception=True
            )

    def test_transition_to_supervisor_requires_scope_and_transition_away_deletes_it(self):
        teacher = User.objects.create_user(
            username="transition-teacher",
            role=User.Role.TEACHER,
        )
        url = f"{self.users_url}{teacher.pk}/"
        missing = self.client.patch(
            url, {"role": User.Role.SUPERVISOR}, format="json"
        )
        self.assertEqual(missing.status_code, 400)
        teacher.refresh_from_db()
        self.assertEqual(teacher.role, User.Role.TEACHER)

        promoted = self.client.patch(
            url,
            {
                "role": User.Role.SUPERVISOR,
                "supervisor_scope": {"scope_type": "all", "stages": []},
            },
            format="json",
        )
        self.assertEqual(promoted.status_code, 200)
        self.assertTrue(SupervisorScope.objects.filter(supervisor=teacher).exists())

        demoted = self.client.patch(
            url, {"role": User.Role.TEACHER}, format="json"
        )
        self.assertEqual(demoted.status_code, 200)
        self.assertFalse(SupervisorScope.objects.filter(supervisor=teacher).exists())

    def test_django_admin_role_is_read_only_for_existing_users(self):
        model_admin = CustomUserAdmin(User, AdminSite())
        self.assertIn("role", model_admin.get_readonly_fields(None, self.admin))
        self.assertNotIn("role", model_admin.get_readonly_fields(None, None))

    def test_django_admin_post_rejects_supervisor_but_allows_other_roles(self):
        root = User.objects.create_superuser(
            username="scope-admin-root",
            password=self.password,
        )
        self.client.force_login(root)
        add_url = reverse("admin:accounts_user_add")
        supervisor_response = self.client.post(
            add_url,
            {
                "username": "admin-created-supervisor",
                "password1": self.password,
                "password2": self.password,
                "role": User.Role.SUPERVISOR,
                "must_change_password": "on",
            },
        )
        self.assertEqual(supervisor_response.status_code, 200)
        self.assertContains(
            supervisor_response,
            "يتم إنشاء الموجّه عبر Accounts API لأن نطاق المراحل "
            "(SupervisorScope) إلزامي.",
        )
        self.assertFalse(
            User.objects.filter(username="admin-created-supervisor").exists()
        )

        teacher_response = self.client.post(
            add_url,
            {
                "username": "admin-created-teacher",
                "password1": self.password,
                "password2": self.password,
                "role": User.Role.TEACHER,
                "must_change_password": "on",
            },
        )
        self.assertEqual(teacher_response.status_code, 302)
        self.assertTrue(
            User.objects.filter(
                username="admin-created-teacher",
                role=User.Role.TEACHER,
            ).exists()
        )


class SupervisorTeacherAccountScopeTests(TestCase):
    password = "TeacherScope!934"
    users_url = "/api/v1/accounts/users/"

    def setUp(self):
        self.client = APIClient()
        self.today = timezone.localdate()
        self.admin = User.objects.create_user(
            username="teacher-scope-admin",
            role=User.Role.SCHOOL_ADMIN,
            password=self.password,
            must_change_password=False,
        )
        self.supervisor = User.objects.create_user(
            username="teacher-scope-supervisor",
            role=User.Role.SUPERVISOR,
            password=self.password,
            must_change_password=False,
        )
        set_supervisor_scope(
            supervisor=self.supervisor,
            scope_type=SupervisorScope.ScopeType.SELECTED_STAGES,
            stages=[GradeLevel.Stage.PRIMARY],
            actor=self.admin,
        )
        self.guardian = User.objects.create_user(
            username="teacher-scope-guardian",
            role=User.Role.GUARDIAN,
        )
        self.teacher_a = self.teacher("scope-teacher-a")
        self.teacher_b = self.teacher("scope-teacher-b")
        self.teacher_c = self.teacher("scope-teacher-c")
        self.teacher_d = self.teacher("scope-teacher-d")
        self.ended_teacher = self.teacher("scope-teacher-ended")

        year = AcademicYear.objects.create(
            start_date=self.today - timedelta(days=100),
            end_date=self.today + timedelta(days=100),
        )
        primary = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY, name="Scope Primary"
        )
        secondary = GradeLevel.objects.create(
            stage=GradeLevel.Stage.SECONDARY, name="Scope Secondary"
        )
        subject = Subject.objects.create(name="Scope Subject")
        self.primary_section = Section.objects.create(
            academic_year=year, grade_level=primary, name="P"
        )
        self.secondary_section = Section.objects.create(
            academic_year=year, grade_level=secondary, name="S"
        )
        self.primary_plan = GradeSubject.objects.create(
            academic_year=year, grade_level=primary, subject=subject
        )
        self.secondary_plan = GradeSubject.objects.create(
            academic_year=year, grade_level=secondary, subject=subject
        )
        self.assign(self.teacher_a, primary=True)
        self.assign(self.teacher_b, primary=True)
        self.assign(self.teacher_b, primary=False)
        self.assign(self.teacher_c, primary=False)
        self.assign(
            self.ended_teacher,
            primary=True,
            end_date=self.today - timedelta(days=1),
        )
        self.client.force_authenticate(self.supervisor, token={"client": "web"})

    def teacher(self, username):
        return User.objects.create_user(
            username=username,
            role=User.Role.TEACHER,
            password=self.password,
            must_change_password=False,
        )

    def assign(self, teacher, *, primary, end_date=None):
        return TeacherAssignment.objects.create(
            teacher=teacher,
            grade_subject=self.primary_plan if primary else self.secondary_plan,
            section=self.primary_section if primary else self.secondary_section,
            start_date=self.today - timedelta(days=30),
            end_date=end_date,
        )

    def detail(self, user):
        return f"{self.users_url}{user.pk}/"

    def listed_usernames(self):
        response = self.client.get(self.users_url)
        self.assertEqual(response.status_code, 200)
        return {
            item["username"] for item in response.data["data"]["results"]
        }

    def test_selected_scope_list_retrieve_and_basic_update(self):
        names = self.listed_usernames()
        self.assertIn(self.teacher_a.username, names)
        self.assertIn(self.teacher_b.username, names)
        self.assertIn(self.guardian.username, names)
        self.assertNotIn(self.teacher_c.username, names)
        self.assertNotIn(self.teacher_d.username, names)
        self.assertNotIn(self.ended_teacher.username, names)

        for teacher in (self.teacher_a, self.teacher_b):
            self.assertEqual(self.client.get(self.detail(teacher)).status_code, 200)
            self.assertEqual(
                self.client.patch(
                    self.detail(teacher),
                    {"first_name": "Scoped"},
                    format="json",
                ).status_code,
                200,
            )
        for teacher in (self.teacher_c, self.teacher_d, self.ended_teacher):
            self.assertEqual(self.client.get(self.detail(teacher)).status_code, 404)
            self.assertEqual(
                self.client.patch(
                    self.detail(teacher), {"first_name": "Denied"}, format="json"
                ).status_code,
                404,
            )

    def test_selected_scope_teacher_role_filter_preserves_visibility_rules(self):
        response = self.client.get(
            self.users_url,
            {"role": User.Role.TEACHER},
        )

        self.assertEqual(response.status_code, 200)
        usernames = {
            item["username"]
            for item in response.data["data"]["results"]
        }
        self.assertEqual(
            usernames,
            {
                self.teacher_a.username,
                self.teacher_b.username,
            },
        )
        self.assertNotIn(self.guardian.username, usernames)

    def test_selected_scope_reset_and_stricter_set_active(self):
        for teacher in (self.teacher_a, self.teacher_b):
            self.assertEqual(
                self.client.post(f"{self.detail(teacher)}reset-password/").status_code,
                200,
            )
        for teacher in (self.teacher_c, self.teacher_d):
            self.assertEqual(
                self.client.post(f"{self.detail(teacher)}reset-password/").status_code,
                404,
            )

        self.assertEqual(
            self.client.post(
                f"{self.detail(self.teacher_a)}set-active/",
                {"is_active": False},
                format="json",
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                f"{self.detail(self.teacher_b)}set-active/",
                {"is_active": False},
                format="json",
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"{self.detail(self.teacher_c)}set-active/",
                {"is_active": False},
                format="json",
            ).status_code,
            404,
        )

    def test_all_scope_and_missing_scope_fail_closed_for_teachers(self):
        set_supervisor_scope(
            supervisor=self.supervisor,
            scope_type=SupervisorScope.ScopeType.ALL,
            stages=[],
            actor=self.admin,
        )
        self.assertEqual(self.client.get(self.detail(self.teacher_d)).status_code, 200)
        self.assertEqual(
            self.client.post(
                f"{self.detail(self.teacher_d)}set-active/",
                {"is_active": False},
                format="json",
            ).status_code,
            200,
        )

        self.supervisor.supervisor_scope.delete()
        self.assertEqual(self.client.get(self.detail(self.teacher_a)).status_code, 404)
        self.assertEqual(self.client.get(self.detail(self.guardian)).status_code, 200)

    def test_selected_supervisor_can_create_and_see_unassigned_teacher(self):
        response = self.client.post(
            self.users_url,
            {"username": "new-unassigned-teacher", "role": User.Role.TEACHER},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        teacher_id = response.data["data"]["id"]
        self.assertIn("temporary_password", response.data["data"])
        teacher = User.objects.get(pk=teacher_id)
        self.assertEqual(teacher.created_by, self.supervisor)
        self.assertEqual(self.client.get(f"{self.users_url}{teacher_id}/").status_code, 200)
        self.assertIn(teacher.username, self.listed_usernames())

    def test_selected_supervisor_can_update_created_guardian_basic_fields(self):
        created = self.client.post(
            self.users_url,
            {
                "username": "supervisor-created-guardian",
                "role": User.Role.GUARDIAN,
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        guardian = User.objects.get(pk=created.data["data"]["id"])
        self.assertEqual(guardian.created_by, self.supervisor)

        updated = self.client.patch(
            self.detail(guardian),
            {
                "first_name": "Guardian Updated",
                "phone_number": "0991000001",
            },
            format="json",
        )

        self.assertEqual(updated.status_code, 200)
        guardian.refresh_from_db()
        self.assertEqual(guardian.first_name, "Guardian Updated")
        self.assertEqual(guardian.phone_number, "0991000001")

    def test_selected_supervisor_can_update_owned_unassigned_teacher_basic_fields(self):
        teacher = self.create_supervisor_teacher(
            "supervisor-created-unassigned-teacher"
        )
        self.assertEqual(teacher.created_by, self.supervisor)
        self.assertFalse(teacher.teaching_assignments.exists())

        updated = self.client.patch(
            self.detail(teacher),
            {
                "first_name": "Teacher Updated",
                "phone_number": "0991000002",
            },
            format="json",
        )

        self.assertEqual(updated.status_code, 200)
        teacher.refresh_from_db()
        self.assertEqual(teacher.first_name, "Teacher Updated")
        self.assertEqual(teacher.phone_number, "0991000002")

    def create_supervisor_teacher(self, username):
        response = self.client.post(
            self.users_url,
            {"username": username, "role": User.Role.TEACHER},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        return User.objects.get(pk=response.data["data"]["id"])

    def test_other_supervisor_cannot_see_owned_unassigned_teacher(self):
        teacher = self.create_supervisor_teacher("owned-by-first-supervisor")
        other = User.objects.create_user(
            username="teacher-scope-other-supervisor",
            role=User.Role.SUPERVISOR,
            password=self.password,
            must_change_password=False,
        )
        set_supervisor_scope(
            supervisor=other,
            scope_type=SupervisorScope.ScopeType.SELECTED_STAGES,
            stages=[GradeLevel.Stage.PRIMARY],
            actor=self.admin,
        )
        self.client.force_authenticate(other, token={"client": "web"})

        self.assertEqual(self.client.get(self.detail(teacher)).status_code, 404)

    def test_admin_created_unassigned_teacher_is_not_visible_by_ownership(self):
        teacher = User.objects.create_user(
            username="admin-created-unassigned-teacher",
            role=User.Role.TEACHER,
            password=self.password,
            created_by=self.admin,
        )

        self.assertEqual(self.client.get(self.detail(teacher)).status_code, 404)

    def test_owned_teacher_with_active_assignment_inside_scope_remains_visible(self):
        teacher = self.create_supervisor_teacher("owned-inside-scope-teacher")
        self.assign(teacher, primary=True)

        self.assertEqual(self.client.get(self.detail(teacher)).status_code, 200)

    def test_owned_teacher_with_active_assignment_outside_scope_is_hidden(self):
        teacher = self.create_supervisor_teacher("owned-outside-scope-teacher")
        self.assign(teacher, primary=False)

        self.assertEqual(self.client.get(self.detail(teacher)).status_code, 404)

    def test_legacy_unassigned_teacher_without_creator_remains_hidden(self):
        legacy = self.teacher("legacy-unassigned-teacher")
        self.assertIsNone(legacy.created_by)

        self.assertEqual(self.client.get(self.detail(legacy)).status_code, 404)

    def test_created_by_does_not_expand_create_permission(self):
        add_user = Permission.objects.get(
            content_type__app_label="accounts",
            codename="add_user",
        )
        self.supervisor.user_permissions.remove(add_user)

        response = self.client.post(
            self.users_url,
            {"username": "permission-denied-teacher", "role": User.Role.TEACHER},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="permission-denied-teacher").exists())

    def test_non_teacher_visibility_rules_are_unchanged(self):
        self.assertIn(self.guardian.username, self.listed_usernames())

    def test_business_permissions_remain_required(self):
        cases = (
            ("accounts.view_user", lambda: self.client.get(self.users_url)),
            (
                "accounts.change_user",
                lambda: self.client.patch(
                    self.detail(self.teacher_a),
                    {"first_name": "Denied"},
                    format="json",
                ),
            ),
            (
                "accounts.reset_user_password",
                lambda: self.client.post(
                    f"{self.detail(self.teacher_a)}reset-password/"
                ),
            ),
            (
                "accounts.set_user_active",
                lambda: self.client.post(
                    f"{self.detail(self.teacher_a)}set-active/",
                    {"is_active": False},
                    format="json",
                ),
            ),
        )
        for code, request in cases:
            app_label, codename = code.split(".", 1)
            permission = Permission.objects.get(
                content_type__app_label=app_label,
                codename=codename,
            )
            self.supervisor.user_permissions.remove(permission)
            with self.subTest(permission=code):
                self.assertEqual(request().status_code, 403)
            self.supervisor.user_permissions.add(permission)

    def test_basic_update_preserves_custom_permissions(self):
        teacher = User.objects.create_user(
            username="basic-update-teacher",
            role=User.Role.TEACHER,
        )
        custom = Permission.objects.get(
            content_type__app_label="students",
            codename="change_student",
        )
        teacher.user_permissions.add(custom)
        before = set(teacher.user_permissions.values_list("pk", flat=True))
        self.client.force_authenticate(self.admin, token={"client": "web"})
        response = self.client.patch(
            f"{self.users_url}{teacher.pk}/",
            {"first_name": "Updated"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(teacher.user_permissions.values_list("pk", flat=True)), before
        )

    def test_role_change_rolls_back_everything_when_scope_write_fails(self):
        teacher = User.objects.create_user(
            username="rollback-teacher",
            role=User.Role.TEACHER,
        )
        before_permissions = set(direct_business_permission_codes(teacher))
        with patch(
            "academics.supervisor_scope_services.set_supervisor_scope",
            side_effect=RuntimeError("scope failure"),
        ):
            with self.assertRaises(RuntimeError):
                change_user_role(
                    target=teacher,
                    new_role=User.Role.SUPERVISOR,
                    actor=self.admin,
                    supervisor_scope={"scope_type": "all", "stages": []},
                )

        teacher.refresh_from_db()
        self.assertEqual(teacher.role, User.Role.TEACHER)
        self.assertEqual(
            set(direct_business_permission_codes(teacher)), before_permissions
        )
        self.assertFalse(SupervisorScope.objects.filter(supervisor=teacher).exists())
