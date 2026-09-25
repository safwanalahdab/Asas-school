from datetime import date

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from academics.models import (
    AcademicYear,
    GradeLevel,
    Section,
    SupervisorScope,
    SupervisorScopeStage,
)
from behavior.models import StudentPointEntry
from students.models import Enrollment, Student


class StudentProfilePointsSummaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.old_year = AcademicYear.objects.create(
            start_date=date(2025, 9, 1),
            end_date=date(2026, 6, 30),
            status=AcademicYear.Status.CLOSED,
        )
        cls.active_year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )
        cls.empty_year = AcademicYear.objects.create(
            start_date=date(2027, 9, 1),
            end_date=date(2028, 6, 30),
            status=AcademicYear.Status.DRAFT,
        )
        cls.primary_grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY,
            name="Profile points primary",
        )
        cls.preparatory_grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PREPARATORY,
            name="Profile points preparatory",
        )
        cls.old_section = Section.objects.create(
            academic_year=cls.old_year,
            grade_level=cls.primary_grade,
            name="Old",
        )
        cls.active_section = Section.objects.create(
            academic_year=cls.active_year,
            grade_level=cls.preparatory_grade,
            name="Active",
        )
        cls.student = Student.objects.create(
            first_name="Profile",
            last_name="Points",
            birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )
        cls.old_enrollment = Enrollment.objects.create(
            student=cls.student,
            academic_year=cls.old_year,
            section=cls.old_section,
            enrollment_date=cls.old_year.start_date,
        )
        cls.active_enrollment = Enrollment.objects.create(
            student=cls.student,
            academic_year=cls.active_year,
            section=cls.active_section,
            enrollment_date=cls.active_year.start_date,
        )
        cls.admin = cls.make_user("profile-points-admin", User.Role.SCHOOL_ADMIN)
        cls.secretariat = cls.make_user(
            "profile-points-secretariat",
            User.Role.SECRETARIAT,
        )
        cls.teacher = cls.make_user("profile-points-teacher", User.Role.TEACHER)
        cls.supervisor = cls.make_user(
            "profile-points-supervisor",
            User.Role.SUPERVISOR,
        )
        cls.outside_supervisor = cls.make_user(
            "profile-points-outside-supervisor",
            User.Role.SUPERVISOR,
        )
        profile_permission = Permission.objects.get(
            content_type__app_label="students",
            codename="view_student_profile",
        )
        for user in (
            cls.admin,
            cls.secretariat,
            cls.teacher,
            cls.supervisor,
            cls.outside_supervisor,
        ):
            user.user_permissions.add(profile_permission)

        scope = SupervisorScope.objects.create(
            supervisor=cls.supervisor,
            scope_type=SupervisorScope.ScopeType.SELECTED_STAGES,
        )
        SupervisorScopeStage.objects.create(
            scope=scope,
            stage=GradeLevel.Stage.PREPARATORY,
        )
        outside_scope = SupervisorScope.objects.create(
            supervisor=cls.outside_supervisor,
            scope_type=SupervisorScope.ScopeType.SELECTED_STAGES,
        )
        SupervisorScopeStage.objects.create(
            scope=outside_scope,
            stage=GradeLevel.Stage.PRIMARY,
        )

    @classmethod
    def make_user(cls, username, role):
        return User.objects.create_user(
            username=username,
            password="StrongPass!123",
            role=role,
            must_change_password=False,
        )

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user, token={"client": "web"})
        return client

    def profile(self, *, user=None, academic_year=None, student=None):
        params = {}
        if academic_year is not None:
            params["academic_year"] = str(academic_year.pk)
        target = student or self.student
        return self.client_for(user or self.admin).get(
            f"/api/v1/students/{target.pk}/profile/",
            params,
        )

    def create_point(self, enrollment, points):
        return StudentPointEntry.objects.create(
            enrollment=enrollment,
            points=points,
            note="نقاط الملف الشامل",
            occurred_on=enrollment.academic_year.start_date,
            created_by=self.admin,
        )

    @staticmethod
    def summary(response):
        return response.data["data"]["points"]["summary"]

    def test_profile_without_point_entries_returns_zero_summary(self):
        response = self.profile()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.summary(response),
            {"total_points": 0, "entries_count": 0},
        )

    def test_profile_sums_multiple_entries_for_selected_enrollment(self):
        self.create_point(self.active_enrollment, 10)
        self.create_point(self.active_enrollment, 25)
        summary = self.summary(self.profile())
        self.assertEqual(summary["total_points"], 35)

    def test_profile_returns_correct_entries_count(self):
        self.create_point(self.active_enrollment, 10)
        self.create_point(self.active_enrollment, 20)
        self.create_point(self.active_enrollment, 5)
        summary = self.summary(self.profile())
        self.assertEqual(summary["entries_count"], 3)

    def test_points_from_another_academic_year_are_excluded(self):
        self.create_point(self.old_enrollment, 30)
        self.create_point(self.active_enrollment, 5)
        self.create_point(self.active_enrollment, 15)
        active_summary = self.summary(self.profile())
        old_summary = self.summary(self.profile(academic_year=self.old_year))
        self.assertEqual(active_summary, {"total_points": 20, "entries_count": 2})
        self.assertEqual(old_summary, {"total_points": 30, "entries_count": 1})

    def test_changing_entry_points_is_reflected_immediately(self):
        entry = self.create_point(self.active_enrollment, 10)
        entry.points = 40
        entry.save(update_fields=["points", "updated_at"])
        self.assertEqual(self.summary(self.profile())["total_points"], 40)

    def test_deleting_entry_is_reflected_immediately(self):
        first = self.create_point(self.active_enrollment, 10)
        self.create_point(self.active_enrollment, 20)
        first.delete()
        self.assertEqual(
            self.summary(self.profile()),
            {"total_points": 20, "entries_count": 1},
        )

    def test_adding_entry_is_reflected_immediately(self):
        self.assertEqual(self.summary(self.profile())["total_points"], 0)
        self.create_point(self.active_enrollment, 15)
        self.assertEqual(
            self.summary(self.profile()),
            {"total_points": 15, "entries_count": 1},
        )

    def test_existing_profile_permissions_remain_unchanged(self):
        self.assertFalse(self.secretariat.user_permissions.filter(
            content_type__app_label="behavior",
            codename="view_studentpointentry",
        ).exists())
        self.assertEqual(self.profile(user=self.secretariat).status_code, 200)
        self.assertEqual(self.profile(user=self.teacher).status_code, 403)

    def test_existing_supervisor_scope_remains_unchanged(self):
        self.create_point(self.active_enrollment, 12)
        allowed = self.profile(user=self.supervisor)
        denied = self.profile(user=self.outside_supervisor)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(self.summary(allowed)["total_points"], 12)
        self.assertEqual(denied.status_code, 404)

    def test_year_without_enrollment_returns_zero_summary(self):
        response = self.profile(academic_year=self.empty_year)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["data"]["enrollment"])
        self.assertEqual(
            self.summary(response),
            {"total_points": 0, "entries_count": 0},
        )
