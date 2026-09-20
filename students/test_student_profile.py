from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, GradeSubject, Section, Subject, SupervisorScope, Term
from accounts.models import User
from accounts.permission_catalog import ALL_MANAGEABLE_PERMISSIONS
from accounts.role_permission_templates import ROLE_PERMISSION_TEMPLATES
from attendance.models import AttendanceRecord, AttendanceSheet
from behavior.models import BehaviorNote
from finance.models import GradeTuitionPlan, Payment, StudentDiscount, StudentFinancialAccount
from grades.models import Assessment, AssessmentSection, StudentScore

from .models import Enrollment, GuardianStudent, Student, StudentHealthProfile


class StudentProfileApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.active_year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )
        cls.old_year = AcademicYear.objects.create(
            start_date=date(2025, 9, 1),
            end_date=date(2026, 6, 30),
            status=AcademicYear.Status.CLOSED,
        )
        cls.grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY,
            name="الصف الخامس",
        )
        cls.section_a = Section.objects.create(
            academic_year=cls.active_year,
            grade_level=cls.grade,
            name="أ",
        )
        cls.section_b = Section.objects.create(
            academic_year=cls.active_year,
            grade_level=cls.grade,
            name="ب",
        )
        cls.old_section = Section.objects.create(
            academic_year=cls.old_year,
            grade_level=cls.grade,
            name="قديمة",
        )
        cls.student = Student.objects.create(
            first_name="أحمد",
            father_name="محمود",
            mother_name="سارة",
            last_name="خالد",
            first_name_en="Ahmad",
            last_name_en="Khaled",
            gender=Student.Gender.MALE,
            birth_date=date(2015, 1, 2),
        )
        cls.enrollment = Enrollment.objects.create(
            student=cls.student,
            academic_year=cls.active_year,
            section=cls.section_b,
            enrollment_date=date(2026, 9, 1),
        )
        cls.old_enrollment = Enrollment.objects.create(
            student=cls.student,
            academic_year=cls.old_year,
            section=cls.old_section,
            enrollment_date=date(2025, 9, 1),
        )
        cls.admin = cls.make_user("profile-admin", User.Role.SCHOOL_ADMIN)
        cls.secretariat = cls.make_user("profile-secretariat", User.Role.SECRETARIAT)
        cls.supervisor = cls.make_user("profile-supervisor", User.Role.SUPERVISOR)
        cls.teacher = cls.make_user("profile-teacher", User.Role.TEACHER)
        cls.tech = cls.make_user("profile-tech", User.Role.TECH_SUPPORT)
        cls.guardian = cls.make_user(
            "profile-guardian",
            User.Role.GUARDIAN,
            first_name="عمر",
            last_name="الحموي",
            phone_number="0999999999",
            email="guardian@example.com",
        )
        cls.root = User.objects.create_superuser(
            username="profile-root",
            password="x",
            must_change_password=False,
        )
        cls.permission = Permission.objects.get(
            content_type__app_label="students",
            codename="view_student_profile",
        )
        for user in (
            cls.admin,
            cls.secretariat,
            cls.supervisor,
            cls.teacher,
            cls.tech,
            cls.guardian,
        ):
            user.user_permissions.clear()
        for user in (cls.admin, cls.secretariat, cls.supervisor):
            user.user_permissions.add(cls.permission)
        SupervisorScope.objects.create(
            supervisor=cls.supervisor,
            scope_type=SupervisorScope.ScopeType.ALL,
        )

        GuardianStudent.objects.create(
            guardian=cls.guardian,
            student=cls.student,
            relationship="الأب",
        )
        StudentHealthProfile.objects.create(
            student=cls.student,
            blood_type="A+",
            allergies="غبار",
        )

        present_sheet = AttendanceSheet.objects.create(
            section=cls.section_a,
            attendance_date=date(2026, 10, 1),
            created_by=cls.admin,
        )
        absent_sheet = AttendanceSheet.objects.create(
            section=cls.section_b,
            attendance_date=date(2026, 10, 2),
            created_by=cls.admin,
        )
        unmarked_sheet = AttendanceSheet.objects.create(
            section=cls.section_b,
            attendance_date=date(2026, 10, 3),
            created_by=cls.admin,
        )
        AttendanceRecord.objects.create(
            sheet=present_sheet,
            enrollment=cls.enrollment,
            status=AttendanceRecord.Status.PRESENT,
        )
        AttendanceRecord.objects.create(
            sheet=absent_sheet,
            enrollment=cls.enrollment,
            status=AttendanceRecord.Status.ABSENT,
            absence_type=AttendanceRecord.AbsenceType.EXCUSED,
            absence_reason="مرض",
            absence_reason_source=AttendanceRecord.AbsenceReasonSource.GUARDIAN,
        )
        AttendanceRecord.objects.create(
            sheet=unmarked_sheet,
            enrollment=cls.enrollment,
            status=AttendanceRecord.Status.UNMARKED,
        )

        subject = Subject.objects.create(name="الرياضيات")
        grade_subject = GradeSubject.objects.create(
            academic_year=cls.active_year,
            grade_level=cls.grade,
            subject=subject,
        )
        term = Term.objects.create(
            academic_year=cls.active_year,
            number=Term.Number.FIRST,
            start_date=date(2026, 9, 1),
            end_date=date(2027, 1, 31),
        )
        published_assessment = Assessment.objects.create(
            grade_subject=grade_subject,
            term=term,
            title="اختبار أول",
            max_score=Decimal("100.00"),
            assessment_date=date(2026, 10, 4),
            created_by=cls.admin,
        )
        draft_assessment = Assessment.objects.create(
            grade_subject=grade_subject,
            term=term,
            title="اختبار ثان",
            max_score=Decimal("50.00"),
            assessment_date=date(2026, 10, 5),
            created_by=cls.admin,
        )
        AssessmentSection.objects.create(
            assessment=published_assessment,
            section=cls.section_a,
            status=AssessmentSection.Status.PUBLISHED,
            published_by=cls.admin,
            published_at=timezone.now(),
        )
        AssessmentSection.objects.create(
            assessment=draft_assessment,
            section=cls.section_b,
            status=AssessmentSection.Status.DRAFT,
        )
        StudentScore.objects.create(
            assessment=published_assessment,
            enrollment=cls.enrollment,
            recorded_section=cls.section_a,
            score=Decimal("90.00"),
            updated_by=cls.admin,
        )
        StudentScore.objects.create(
            assessment=draft_assessment,
            enrollment=cls.enrollment,
            recorded_section=cls.section_b,
            score=Decimal("40.00"),
            updated_by=cls.admin,
        )

        BehaviorNote.objects.create(
            enrollment=cls.enrollment,
            note_type=BehaviorNote.Type.POSITIVE,
            title="تعاون",
            description="متعاون",
            occurred_on=date(2026, 10, 1),
            created_by=cls.admin,
        )
        BehaviorNote.objects.create(
            enrollment=cls.enrollment,
            note_type=BehaviorNote.Type.NEGATIVE,
            title="تأخر",
            description="تأخر عن الحصة",
            occurred_on=date(2026, 10, 2),
            created_by=cls.admin,
        )

        tuition_plan = GradeTuitionPlan.objects.create(
            academic_year=cls.active_year,
            grade_level=cls.grade,
            base_tuition_usd=Decimal("1000.00"),
            created_by=cls.admin,
        )
        cls.account = StudentFinancialAccount.objects.create(
            enrollment=cls.enrollment,
            tuition_plan=tuition_plan,
            created_by=cls.admin,
        )
        Payment.objects.create(
            account=cls.account,
            currency="usd",
            amount=Decimal("300.00"),
            equivalent_usd=Decimal("300.00"),
            recorded_by=cls.admin,
        )
        Payment.objects.create(
            account=cls.account,
            currency="syp",
            amount=Decimal("500000.00"),
            exchange_rate_syp_per_usd=Decimal("10000.0000"),
            equivalent_usd=Decimal("50.00"),
            recorded_by=cls.admin,
            is_cancelled=True,
            cancellation_reason="ملغاة",
            cancelled_by=cls.admin,
            cancelled_at=timezone.now(),
        )
        StudentDiscount.objects.create(
            account=cls.account,
            discount_type=StudentDiscount.DiscountType.FIXED,
            value=Decimal("100.00"),
            currency="usd",
            equivalent_usd=Decimal("100.00"),
            reason="حسم",
            created_by=cls.admin,
        )

    @classmethod
    def make_user(cls, username, role, **extra):
        return User.objects.create_user(
            username=username,
            password="x",
            role=role,
            must_change_password=False,
            **extra,
        )

    def client_for(self, user, token=None):
        client = APIClient()
        client.force_authenticate(user, token=token or {"client": "web"})
        return client

    @property
    def url(self):
        return f"/api/v1/students/{self.student.id}/profile/"

    def get_data(self, user=None, **params):
        response = self.client_for(user or self.admin).get(self.url, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]

    def test_allowed_roles_and_superuser_can_view(self):
        for user in (self.admin, self.secretariat, self.supervisor, self.root):
            with self.subTest(role=user.role):
                self.assertEqual(self.client_for(user).get(self.url).status_code, 200)

    def test_allowed_role_still_requires_profile_permission(self):
        self.admin.user_permissions.remove(self.permission)
        self.assertEqual(self.client_for(self.admin).get(self.url).status_code, 403)

    def test_role_ceiling_blocks_teacher_tech_support_and_guardian(self):
        self.teacher.user_permissions.add(self.permission)
        self.tech.user_permissions.add(self.permission)
        self.guardian.user_permissions.add(self.permission)
        for user in (self.teacher, self.tech, self.guardian):
            with self.subTest(role=user.role):
                self.assertEqual(self.client_for(user).get(self.url).status_code, 403)

    def test_anonymous_mobile_and_password_change_are_blocked(self):
        self.assertEqual(APIClient().get(self.url).status_code, 401)
        self.assertEqual(
            self.client_for(self.admin, {"client": "mobile"}).get(self.url).status_code,
            403,
        )
        self.admin.must_change_password = True
        self.admin.save(update_fields=["must_change_password"])
        self.assertEqual(self.client_for(self.admin).get(self.url).status_code, 403)

    def test_missing_student_is_404(self):
        response = self.client_for(self.admin).get(
            "/api/v1/students/00000000-0000-0000-0000-000000000000/profile/"
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["code"], "STUDENT_NOT_FOUND")

    def test_academic_year_selection_and_validation(self):
        self.assertEqual(self.get_data()["academic_year"]["id"], str(self.active_year.id))
        old = self.get_data(academic_year=self.old_year.id)
        self.assertEqual(old["enrollment"]["id"], str(self.old_enrollment.id))
        for value in ("not-a-uuid", "00000000-0000-0000-0000-000000000000"):
            with self.subTest(value=value):
                response = self.client_for(self.admin).get(self.url, {"academic_year": value})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data["code"], "INVALID_ACADEMIC_YEAR")

    def test_no_active_year_returns_successful_empty_annual_data(self):
        AcademicYear.objects.filter(pk=self.active_year.pk).update(
            status=AcademicYear.Status.CLOSED
        )
        data = self.get_data()
        self.assertIsNone(data["academic_year"])
        self.assertIsNone(data["enrollment"])
        self.assertEqual(data["attendance"]["summary"]["total_recorded_days"], 0)
        self.assertEqual(data["grades"]["count"], 0)
        self.assertEqual(data["behavior"]["notes"]["count"], 0)
        self.assertIsNone(data["finance"]["account"])

    def test_student_guardian_health_and_enrollment_contract(self):
        data = self.get_data()
        self.assertEqual(data["student"]["full_name"], "أحمد خالد")
        self.assertNotIn("national_id", data["student"])
        self.assertEqual(data["guardians"][0]["full_name"], "عمر الحموي")
        self.assertNotIn("password", data["guardians"][0])
        self.assertEqual(data["health_profile"]["blood_type"], "A+")
        self.assertEqual(data["enrollment"]["grade_level"]["name"], "الصف الخامس")

    def test_inactive_guardian_account_is_still_visible(self):
        self.guardian.is_active = False
        self.guardian.save(update_fields=["is_active"])
        guardian = self.get_data()["guardians"][0]
        self.assertFalse(guardian["is_active"])

    def test_attendance_summary_excludes_unmarked_and_keeps_old_section(self):
        attendance = self.get_data()["attendance"]
        self.assertEqual(attendance["summary"]["total_recorded_days"], 2)
        self.assertEqual(attendance["summary"]["present_count"], 1)
        self.assertEqual(attendance["summary"]["absent_count"], 1)
        self.assertEqual(attendance["summary"]["attendance_rate_percentage"], "50.00")
        self.assertEqual(attendance["records"]["count"], 2)
        self.assertIn("أ", {row["section"]["name"] for row in attendance["records"]["results"]})

    def test_grades_include_published_and_draft_without_n_plus_one(self):
        with CaptureQueriesContext(connection) as one_result_queries:
            self.get_data(grades_page_size=1)
        with CaptureQueriesContext(connection) as two_result_queries:
            grades = self.get_data(grades_page_size=2)["grades"]
        self.assertEqual(len(one_result_queries), len(two_result_queries))
        self.assertEqual(grades["count"], 2)
        self.assertEqual(
            {row["publication_status"] for row in grades["results"]},
            {"published", "draft"},
        )

    def test_behavior_and_finance_summaries(self):
        data = self.get_data()
        self.assertEqual(data["behavior"]["summary"]["positive_notes_count"], 1)
        self.assertEqual(data["behavior"]["summary"]["negative_notes_count"], 1)
        self.assertEqual(data["finance"]["summary"]["net_tuition_usd"], "900.00")
        self.assertEqual(data["finance"]["summary"]["total_paid_usd"], "300.00")
        self.assertEqual(data["finance"]["payments"]["count"], 2)
        cancelled = [row for row in data["finance"]["payments"]["results"] if row["is_cancelled"]]
        self.assertEqual(cancelled[0]["equivalent_usd"], "50.00")

    def test_profile_permission_does_not_grant_original_finance_endpoint(self):
        self.assertEqual(self.client_for(self.supervisor).get(self.url).status_code, 200)
        response = self.client_for(self.supervisor).get("/api/v1/finance/accounts/")
        self.assertEqual(response.status_code, 403)

    def test_missing_enrollment_returns_empty_annual_sections(self):
        student = Student.objects.create(
            first_name="غير",
            last_name="مسجل",
            birth_date=date(2016, 1, 1),
            gender=Student.Gender.FEMALE,
        )
        url = f"/api/v1/students/{student.id}/profile/"
        response = self.client_for(self.admin).get(url)
        self.assertEqual(response.status_code, 200)
        data = response.data["data"]
        self.assertIsNone(data["enrollment"])
        self.assertEqual(data["grades"]["count"], 0)
        self.assertIsNone(data["finance"]["account"])

    def test_get_does_not_create_health_or_financial_records(self):
        student = Student.objects.create(
            first_name="بلا",
            last_name="ملفات",
            birth_date=date(2016, 2, 1),
            gender=Student.Gender.MALE,
        )
        enrollment = Enrollment.objects.create(
            student=student,
            academic_year=self.active_year,
            section=self.section_a,
            enrollment_date=date(2026, 9, 2),
        )
        response = self.client_for(self.admin).get(
            f"/api/v1/students/{student.id}/profile/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["data"]["health_profile"])
        self.assertFalse(StudentHealthProfile.objects.filter(student=student).exists())
        self.assertFalse(StudentFinancialAccount.objects.filter(enrollment=enrollment).exists())

    def test_independent_pagination_and_invalid_values(self):
        data = self.get_data(attendance_page_size=1, grades_page_size=2)
        self.assertEqual(data["attendance"]["records"]["page_size"], 1)
        self.assertEqual(data["grades"]["page_size"], 2)
        for params in (
            {"attendance_page": 0},
            {"grades_page": "x"},
            {"behavior_page_size": 101},
            {"payments_page_size": 0},
            {"discounts_page": 2},
        ):
            with self.subTest(params=params):
                response = self.client_for(self.admin).get(self.url, params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data["code"], "INVALID_PROFILE_PAGINATION")

    def test_unsupported_methods_return_405(self):
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client_for(self.admin), method)(self.url, {})
                self.assertEqual(response.status_code, 405)

    def test_permission_catalog_and_role_templates(self):
        code = "students.view_student_profile"
        self.assertIn(code, ALL_MANAGEABLE_PERMISSIONS)
        for role in (
            User.Role.SCHOOL_ADMIN,
            User.Role.SECRETARIAT,
            User.Role.SUPERVISOR,
        ):
            self.assertIn(code, ROLE_PERMISSION_TEMPLATES[role])
        for role in (User.Role.TEACHER, User.Role.GUARDIAN, User.Role.TECH_SUPPORT):
            self.assertNotIn(code, ROLE_PERMISSION_TEMPLATES[role])
