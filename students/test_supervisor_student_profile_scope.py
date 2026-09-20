from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from academics.models import (
    AcademicYear,
    GradeLevel,
    GradeSubject,
    Section,
    Subject,
    SupervisorScope,
    SupervisorScopeStage,
    Term,
)
from attendance.models import AttendanceRecord, AttendanceSheet
from behavior.models import BehaviorNote
from finance.models import GradeTuitionPlan, Payment, StudentFinancialAccount
from grades.models import Assessment, AssessmentSection, StudentScore
from students.models import Enrollment, GuardianStudent, Student, StudentHealthProfile


class SupervisorStudentProfileScopeTests(TestCase):
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
        cls.primary = GradeLevel.objects.create(stage="primary", name="Primary")
        cls.preparatory = GradeLevel.objects.create(
            stage="preparatory", name="Preparatory"
        )
        cls.secondary = GradeLevel.objects.create(stage="secondary", name="Secondary")
        cls.old_primary = Section.objects.create(
            academic_year=cls.old_year, grade_level=cls.primary, name="Old Primary"
        )
        cls.active_preparatory = Section.objects.create(
            academic_year=cls.active_year,
            grade_level=cls.preparatory,
            name="Current Preparatory",
        )
        cls.active_secondary = Section.objects.create(
            academic_year=cls.active_year,
            grade_level=cls.secondary,
            name="Current Secondary",
        )
        cls.student = cls.make_student("Scoped")
        cls.old_enrollment = cls.enroll(cls.student, cls.old_year, cls.old_primary)
        cls.active_enrollment = cls.enroll(
            cls.student, cls.active_year, cls.active_preparatory
        )
        cls.outside_student = cls.make_student("Outside")
        cls.enroll(cls.outside_student, cls.active_year, cls.active_secondary)
        cls.unenrolled = cls.make_student("Unenrolled")

        cls.guardian = cls.make_user("profile-scope-guardian", User.Role.GUARDIAN)
        GuardianStudent.objects.create(guardian=cls.guardian, student=cls.student)
        StudentHealthProfile.objects.create(student=cls.student, blood_type="O+")

        cls.admin = cls.make_user("profile-scope-admin", User.Role.SCHOOL_ADMIN)
        cls.secretariat = cls.make_user(
            "profile-scope-secretariat", User.Role.SECRETARIAT
        )
        cls.primary_supervisor = cls.scoped_supervisor(
            "profile-scope-primary", ["primary"]
        )
        cls.preparatory_supervisor = cls.scoped_supervisor(
            "profile-scope-preparatory", ["preparatory"]
        )
        cls.multi_supervisor = cls.scoped_supervisor(
            "profile-scope-multi", ["primary", "preparatory"]
        )
        cls.all_supervisor = cls.make_user(
            "profile-scope-all", User.Role.SUPERVISOR
        )
        SupervisorScope.objects.create(
            supervisor=cls.all_supervisor, scope_type=SupervisorScope.ScopeType.ALL
        )
        cls.missing_supervisor = cls.make_user(
            "profile-scope-missing", User.Role.SUPERVISOR
        )
        cls.teacher = cls.make_user("profile-scope-teacher", User.Role.TEACHER)
        cls.accountant = cls.make_user(
            "profile-scope-accountant", User.Role.ACCOUNTANT
        )
        cls.root = User.objects.create_superuser(
            username="profile-scope-root", password="x", must_change_password=False
        )
        cls.profile_permission = Permission.objects.get(
            content_type__app_label="students", codename="view_student_profile"
        )
        for user in (
            cls.admin,
            cls.secretariat,
            cls.primary_supervisor,
            cls.preparatory_supervisor,
            cls.multi_supervisor,
            cls.all_supervisor,
            cls.missing_supervisor,
        ):
            user.user_permissions.add(cls.profile_permission)

        sheet = AttendanceSheet.objects.create(
            section=cls.old_primary,
            attendance_date=date(2025, 10, 1),
            created_by=cls.admin,
        )
        AttendanceRecord.objects.create(
            sheet=sheet,
            enrollment=cls.old_enrollment,
            status=AttendanceRecord.Status.PRESENT,
        )
        BehaviorNote.objects.create(
            enrollment=cls.old_enrollment,
            note_type=BehaviorNote.Type.POSITIVE,
            title="Historical behavior",
            description="Visible historical behavior",
            occurred_on=date(2025, 10, 2),
            created_by=cls.admin,
        )
        subject = Subject.objects.create(name="Historical Subject")
        grade_subject = GradeSubject.objects.create(
            academic_year=cls.old_year,
            grade_level=cls.primary,
            subject=subject,
        )
        term = Term.objects.create(
            academic_year=cls.old_year,
            number=Term.Number.FIRST,
            start_date=date(2025, 9, 1),
            end_date=date(2026, 1, 31),
        )
        assessment = Assessment.objects.create(
            grade_subject=grade_subject,
            term=term,
            title="Historical draft",
            max_score=Decimal("100.00"),
            assessment_date=date(2025, 10, 3),
            created_by=cls.admin,
        )
        AssessmentSection.objects.create(
            assessment=assessment,
            section=cls.old_primary,
            status=AssessmentSection.Status.DRAFT,
        )
        StudentScore.objects.create(
            assessment=assessment,
            enrollment=cls.old_enrollment,
            recorded_section=cls.old_primary,
            score=Decimal("88.00"),
            updated_by=cls.admin,
        )
        tuition_plan = GradeTuitionPlan.objects.create(
            academic_year=cls.old_year,
            grade_level=cls.primary,
            base_tuition_usd=Decimal("500.00"),
            created_by=cls.admin,
        )
        account = StudentFinancialAccount.objects.create(
            enrollment=cls.old_enrollment,
            tuition_plan=tuition_plan,
            created_by=cls.admin,
        )
        Payment.objects.create(
            account=account,
            currency="usd",
            amount=Decimal("100.00"),
            equivalent_usd=Decimal("100.00"),
            recorded_by=cls.admin,
        )

    @classmethod
    def make_student(cls, first_name):
        return Student.objects.create(
            first_name=first_name,
            last_name="Student",
            birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )

    @classmethod
    def enroll(cls, student, year, section):
        return Enrollment.objects.create(
            student=student,
            academic_year=year,
            section=section,
            enrollment_date=year.start_date,
        )

    @classmethod
    def make_user(cls, username, role):
        return User.objects.create_user(
            username=username,
            password="x",
            role=role,
            must_change_password=False,
        )

    @classmethod
    def scoped_supervisor(cls, username, stages):
        user = cls.make_user(username, User.Role.SUPERVISOR)
        scope = SupervisorScope.objects.create(
            supervisor=user,
            scope_type=SupervisorScope.ScopeType.SELECTED_STAGES,
        )
        SupervisorScopeStage.objects.bulk_create(
            [SupervisorScopeStage(scope=scope, stage=stage) for stage in stages]
        )
        return user

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user, token={"client": "web"})
        return client

    def profile_url(self, student=None):
        return f"/api/v1/students/{(student or self.student).pk}/profile/"

    def test_current_stage_opens_profile_and_historical_stage_does_not_gate_year(self):
        client = self.client_for(self.preparatory_supervisor)
        current = client.get(self.profile_url())
        self.assertEqual(current.status_code, 200)
        self.assertEqual(
            current.data["data"]["enrollment"]["id"], str(self.active_enrollment.pk)
        )
        historical = client.get(
            self.profile_url(), {"academic_year": str(self.old_year.pk)}
        )
        self.assertEqual(historical.status_code, 200)
        data = historical.data["data"]
        self.assertEqual(data["enrollment"]["id"], str(self.old_enrollment.pk))
        self.assertEqual(data["attendance"]["records"]["count"], 1)
        self.assertEqual(data["grades"]["count"], 1)
        self.assertEqual(data["grades"]["results"][0]["publication_status"], "draft")
        self.assertEqual(data["behavior"]["notes"]["count"], 1)
        self.assertEqual(data["finance"]["payments"]["count"], 1)
        self.assertEqual(data["health_profile"]["blood_type"], "O+")

    def test_historical_stage_cannot_open_profile_when_current_stage_is_outside(self):
        client = self.client_for(self.primary_supervisor)
        for params in ({}, {"academic_year": str(self.old_year.pk)}):
            with self.subTest(params=params):
                self.assertEqual(
                    client.get(self.profile_url(), params).status_code, 404
                )

    def test_outside_uuid_rejected_before_subordinate_selectors(self):
        client = self.client_for(self.primary_supervisor)
        with (
            patch("students.profile_views.get_profile_academic_year") as year_selector,
            patch("students.profile_views.get_profile_guardians") as guardians_selector,
            patch("students.profile_views.get_profile_health") as health_selector,
            patch("students.profile_views.get_profile_enrollment") as enrollment_selector,
        ):
            response = client.get(self.profile_url(self.outside_student))
        self.assertEqual(response.status_code, 404)
        year_selector.assert_not_called()
        guardians_selector.assert_not_called()
        health_selector.assert_not_called()
        enrollment_selector.assert_not_called()

    def test_all_multi_missing_unenrolled_and_no_active_year(self):
        self.assertEqual(
            self.client_for(self.multi_supervisor).get(self.profile_url()).status_code,
            200,
        )
        self.assertEqual(
            self.client_for(self.all_supervisor)
            .get(self.profile_url(self.unenrolled))
            .status_code,
            200,
        )
        self.assertEqual(
            self.client_for(self.missing_supervisor).get(self.profile_url()).status_code,
            404,
        )
        self.assertEqual(
            self.client_for(self.preparatory_supervisor)
            .get(self.profile_url(self.unenrolled))
            .status_code,
            404,
        )
        AcademicYear.objects.filter(pk=self.active_year.pk).update(
            status=AcademicYear.Status.CLOSED
        )
        self.assertEqual(
            self.client_for(self.preparatory_supervisor)
            .get(self.profile_url())
            .status_code,
            404,
        )

    def test_year_without_enrollment_keeps_current_empty_contract(self):
        response = self.client_for(self.preparatory_supervisor).get(
            self.profile_url(), {"academic_year": str(self.empty_year.pk)}
        )
        self.assertEqual(response.status_code, 200)
        data = response.data["data"]
        self.assertIsNone(data["enrollment"])
        self.assertEqual(data["attendance"]["records"]["count"], 0)
        self.assertEqual(data["grades"]["count"], 0)
        self.assertEqual(data["behavior"]["notes"]["count"], 0)
        self.assertIsNone(data["finance"]["account"])

    def test_profile_permission_remains_required_and_finance_permission_is_not(self):
        client = self.client_for(self.preparatory_supervisor)
        self.assertFalse(
            self.preparatory_supervisor.user_permissions.filter(
                content_type__app_label="finance"
            ).exists()
        )
        response = client.get(
            self.profile_url(), {"academic_year": str(self.old_year.pk)}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data["data"]["finance"]["account"])
        self.preparatory_supervisor.user_permissions.remove(self.profile_permission)
        self.assertEqual(client.get(self.profile_url()).status_code, 403)

    def test_student_and_enrollment_endpoints_keep_independent_history_rules(self):
        primary_client = self.client_for(self.primary_supervisor)
        primary_client_user = self.primary_supervisor
        primary_client_user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="students", codename="view_student"
            ),
            Permission.objects.get(
                content_type__app_label="students", codename="view_enrollment"
            ),
        )
        self.assertEqual(
            primary_client.get(
                f"/api/v1/students/students/{self.student.pk}/"
            ).status_code,
            404,
        )
        self.assertEqual(
            primary_client.get(
                f"/api/v1/students/enrollments/{self.old_enrollment.pk}/"
            ).status_code,
            200,
        )

    def test_role_ceiling_and_existing_admin_access_are_unchanged(self):
        for user in (self.admin, self.secretariat, self.root):
            with self.subTest(role=user.role):
                self.assertEqual(
                    self.client_for(user).get(self.profile_url()).status_code, 200
                )
        for user in (self.teacher, self.guardian, self.accountant):
            user.user_permissions.add(self.profile_permission)
            with self.subTest(blocked_role=user.role):
                self.assertEqual(
                    self.client_for(user).get(self.profile_url()).status_code, 403
                )
