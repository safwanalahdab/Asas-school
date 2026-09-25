from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from academics.models import (
    AcademicYear,
    GradeLevel,
    Section,
    SupervisorScope,
    SupervisorScopeStage,
)
from accounts.role_permission_templates import ROLE_PERMISSION_TEMPLATES
from students.models import Enrollment, Student

from .models import StudentPointEntry


User = get_user_model()


class StudentPointEntryWebApiTests(TestCase):
    url = "/api/v1/behavior/points/"

    def setUp(self):
        self.client = APIClient()
        self.admin = self.make_user("points-admin", User.Role.SCHOOL_ADMIN)
        self.secretariat = self.make_user("points-secretariat", User.Role.SECRETARIAT)
        self.supervisor = self.make_user("points-supervisor", User.Role.SUPERVISOR)
        self.admin.user_permissions.clear()
        self.secretariat.user_permissions.clear()
        self.supervisor.user_permissions.clear()
        self.grant(
            self.admin,
            "view_studentpointentry",
            "add_studentpointentry",
            "change_studentpointentry",
            "delete_studentpointentry",
        )
        self.grant(
            self.supervisor,
            "view_studentpointentry",
            "add_studentpointentry",
            "change_studentpointentry",
            "delete_studentpointentry",
        )

        self.year = AcademicYear.objects.create(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        self.other_year = AcademicYear.objects.create(
            start_date=date(2027, 1, 1),
            end_date=date(2027, 12, 31),
        )
        self.primary_grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY,
            name="Points primary",
        )
        self.preparatory_grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PREPARATORY,
            name="Points preparatory",
        )
        self.primary_section = Section.objects.create(
            academic_year=self.year,
            grade_level=self.primary_grade,
            name="A",
        )
        self.preparatory_section = Section.objects.create(
            academic_year=self.other_year,
            grade_level=self.preparatory_grade,
            name="B",
        )
        self.primary_enrollment = self.make_enrollment(
            "Ahmad",
            "Primary",
            self.year,
            self.primary_section,
        )
        self.preparatory_enrollment = self.make_enrollment(
            "Rama",
            "Preparatory",
            self.other_year,
            self.preparatory_section,
        )
        self.primary_point = self.make_point(
            self.primary_enrollment,
            10,
            "تميز في النشاط",
            date(2026, 2, 1),
        )
        self.preparatory_point = self.make_point(
            self.preparatory_enrollment,
            20,
            "تعاون مميز",
            date(2026, 3, 1),
        )

    @staticmethod
    def make_user(username, role, *, must_change_password=False):
        return User.objects.create_user(
            username=username,
            password="StrongPass!123",
            role=role,
            must_change_password=must_change_password,
        )

    @staticmethod
    def grant(user, *codenames):
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="behavior",
            codename__in=codenames,
        ))

    @staticmethod
    def make_enrollment(first_name, last_name, year, section):
        student = Student.objects.create(
            first_name=first_name,
            last_name=last_name,
            birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )
        return Enrollment.objects.create(
            student=student,
            academic_year=year,
            section=section,
            enrollment_date=year.start_date,
        )

    def make_point(self, enrollment, points, note, occurred_on):
        return StudentPointEntry.objects.create(
            enrollment=enrollment,
            points=points,
            note=note,
            occurred_on=occurred_on,
            created_by=self.admin,
        )

    def authenticate(self, user, *, client="web"):
        self.client.force_authenticate(user, token={"client": client})

    def payload(self, enrollment=None, **overrides):
        data = {
            "enrollment": str((enrollment or self.primary_enrollment).pk),
            "points": 15,
            "note": "مشاركة فعالة",
            "occurred_on": "2026-04-01",
        }
        data.update(overrides)
        return data

    def detail(self, point):
        return f"{self.url}{point.pk}/"

    @staticmethod
    def rows(response):
        data = response.data["data"]
        return data.get("results", data) if isinstance(data, dict) else data

    def set_supervisor_scope(self, *stages):
        scope, _ = SupervisorScope.objects.update_or_create(
            supervisor=self.supervisor,
            defaults={
                "scope_type": (
                    SupervisorScope.ScopeType.SELECTED_STAGES
                    if stages
                    else SupervisorScope.ScopeType.ALL
                )
            },
        )
        scope.stages.all().delete()
        for stage in stages:
            SupervisorScopeStage.objects.create(scope=scope, stage=stage)

    def test_school_admin_can_view_points(self):
        self.authenticate(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_school_admin_can_add_points(self):
        self.authenticate(self.admin)
        self.assertEqual(self.client.post(self.url, self.payload(), format="json").status_code, 201)

    def test_school_admin_can_change_points(self):
        self.authenticate(self.admin)
        response = self.client.patch(self.detail(self.primary_point), {"points": 30}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_school_admin_can_delete_points(self):
        self.authenticate(self.admin)
        self.assertEqual(self.client.delete(self.detail(self.primary_point)).status_code, 200)

    def test_secretariat_without_permission_is_denied(self):
        self.authenticate(self.secretariat)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_custom_view_permission_allows_reading(self):
        self.grant(self.secretariat, "view_studentpointentry")
        self.authenticate(self.secretariat)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_custom_add_permission_allows_creation(self):
        self.grant(self.secretariat, "add_studentpointentry")
        self.authenticate(self.secretariat)
        self.assertEqual(self.client.post(self.url, self.payload(), format="json").status_code, 201)

    def test_add_permission_does_not_grant_change_or_delete(self):
        self.grant(self.secretariat, "add_studentpointentry")
        self.authenticate(self.secretariat)
        detail = self.detail(self.primary_point)
        self.assertEqual(self.client.patch(detail, {"points": 40}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(detail).status_code, 403)

    def test_supervisor_lists_only_points_in_assigned_stages(self):
        self.set_supervisor_scope(GradeLevel.Stage.PRIMARY)
        self.authenticate(self.supervisor)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {row["id"] for row in self.rows(response)},
            {str(self.primary_point.pk)},
        )

    def test_supervisor_cannot_retrieve_point_outside_scope(self):
        self.set_supervisor_scope(GradeLevel.Stage.PRIMARY)
        self.authenticate(self.supervisor)
        self.assertEqual(self.client.get(self.detail(self.preparatory_point)).status_code, 404)

    def test_supervisor_cannot_create_point_outside_scope(self):
        self.set_supervisor_scope(GradeLevel.Stage.PRIMARY)
        self.authenticate(self.supervisor)
        response = self.client.post(
            self.url,
            self.payload(self.preparatory_enrollment),
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_supervisor_cannot_patch_point_outside_scope(self):
        self.set_supervisor_scope(GradeLevel.Stage.PRIMARY)
        self.authenticate(self.supervisor)
        self.assertEqual(
            self.client.patch(self.detail(self.preparatory_point), {"points": 50}, format="json").status_code,
            404,
        )

    def test_supervisor_cannot_delete_point_outside_scope(self):
        self.set_supervisor_scope(GradeLevel.Stage.PRIMARY)
        self.authenticate(self.supervisor)
        self.assertEqual(self.client.delete(self.detail(self.preparatory_point)).status_code, 404)

    def test_supervisor_cannot_move_point_to_enrollment_outside_scope(self):
        self.set_supervisor_scope(GradeLevel.Stage.PRIMARY)
        self.authenticate(self.supervisor)
        response = self.client.patch(
            self.detail(self.primary_point),
            {"enrollment": str(self.preparatory_enrollment.pk)},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_created_by_is_assigned_from_request_user(self):
        self.authenticate(self.admin)
        response = self.client.post(self.url, self.payload(), format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(StudentPointEntry.objects.get(pk=response.data["data"]["id"]).created_by, self.admin)

    def test_created_by_cannot_be_forged(self):
        self.authenticate(self.admin)
        response = self.client.post(
            self.url,
            self.payload(created_by=str(self.secretariat.pk)),
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(StudentPointEntry.objects.get(pk=response.data["data"]["id"]).created_by, self.admin)

    def test_authentication_is_required(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_mobile_token_cannot_use_web_points_api(self):
        self.authenticate(self.admin, client="mobile")
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_must_change_password_gate_is_preserved(self):
        user = self.make_user(
            "points-password-change",
            User.Role.SECRETARIAT,
            must_change_password=True,
        )
        self.grant(user, "view_studentpointentry")
        self.authenticate(user)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_points_outside_allowed_range_are_rejected(self):
        self.authenticate(self.admin)
        for points in (0, 101):
            with self.subTest(points=points):
                self.assertEqual(
                    self.client.post(self.url, self.payload(points=points), format="json").status_code,
                    400,
                )

    def test_empty_and_whitespace_notes_are_rejected(self):
        self.authenticate(self.admin)
        for note in ("", "   "):
            with self.subTest(note=repr(note)):
                self.assertEqual(
                    self.client.post(self.url, self.payload(note=note), format="json").status_code,
                    400,
                )

    def test_invalid_date_range_is_rejected(self):
        self.authenticate(self.admin)
        response = self.client.get(self.url, {"date_from": "2026-03-02", "date_to": "2026-03-01"})
        self.assertEqual(response.status_code, 400)

    def test_filters_work(self):
        self.authenticate(self.admin)
        response = self.client.get(self.url, {
            "student": str(self.primary_enrollment.student_id),
            "academic_year": str(self.year.pk),
            "section": str(self.primary_section.pk),
            "date_from": "2026-01-01",
            "date_to": "2026-02-28",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row["id"] for row in self.rows(response)}, {str(self.primary_point.pk)})

    def test_search_works_for_student_name_and_note(self):
        self.authenticate(self.admin)
        by_name = self.client.get(self.url, {"search": "Ahmad"})
        by_note = self.client.get(self.url, {"search": "تعاون"})
        self.assertEqual({row["id"] for row in self.rows(by_name)}, {str(self.primary_point.pk)})
        self.assertEqual({row["id"] for row in self.rows(by_note)}, {str(self.preparatory_point.pk)})

    def test_ordering_works(self):
        self.authenticate(self.admin)
        response = self.client.get(self.url, {"ordering": "points"})
        self.assertEqual(
            [row["points"] for row in self.rows(response)],
            [10, 20],
        )

    def test_put_is_not_allowed(self):
        self.authenticate(self.admin)
        self.assertEqual(self.client.put(self.detail(self.primary_point), {}, format="json").status_code, 405)

    def test_role_templates_include_points_only_for_expected_roles(self):
        permissions = {
            f"behavior.{action}_studentpointentry"
            for action in ("view", "add", "change", "delete")
        }
        self.assertTrue(permissions <= ROLE_PERMISSION_TEMPLATES[User.Role.SCHOOL_ADMIN])
        self.assertTrue(permissions <= ROLE_PERMISSION_TEMPLATES[User.Role.SUPERVISOR])
        for role in (
            User.Role.SECRETARIAT,
            User.Role.TEACHER,
            User.Role.ACCOUNTANT,
            User.Role.GUARDIAN,
            User.Role.TECH_SUPPORT,
        ):
            self.assertTrue(permissions.isdisjoint(ROLE_PERMISSION_TEMPLATES[role]))
