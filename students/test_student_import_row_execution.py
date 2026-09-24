from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from academics.models import AcademicYear, GradeLevel, Section
from finance.models import GradeTuitionPlan, StudentFinancialAccount
from students.models import (
    Enrollment,
    GuardianStudent,
    Student,
    StudentHealthProfile,
    StudentImportJob,
    StudentImportRow,
)
from students.student_import_row_execution import (
    StudentImportRowExecutionError,
    execute_student_import_row,
)


User = get_user_model()


class StudentImportRowExecutionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = User.objects.create_user(
            username="student-import-executor",
            role=User.Role.SCHOOL_ADMIN,
        )
        cls.academic_year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )
        cls.grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY,
            name="الصف الثالث",
        )
        cls.section = Section.objects.create(
            academic_year=cls.academic_year,
            grade_level=cls.grade,
            name="أ",
        )
        cls.tuition_plan = GradeTuitionPlan.objects.create(
            academic_year=cls.academic_year,
            grade_level=cls.grade,
            base_tuition_usd=Decimal("500.00"),
            created_by=cls.actor,
        )

    def normalized_data(
        self,
        *,
        first_name="رامي",
        guardian=None,
    ):
        return {
            "student": {
                "first_name": first_name,
                "last_name": "اختبار",
                "first_name_en": "",
                "last_name_en": "",
                "father_name": "ماهر",
                "mother_name": "هند",
                "birth_date": "2018-05-10",
                "gender": Student.Gender.MALE,
            },
            "guardian": guardian,
            "health_profile": {
                "blood_type": "O+",
                "chronic_diseases": "",
                "allergies": "",
                "permanent_medications": "",
                "special_health_needs": "",
                "emergency_contact_name": "",
                "emergency_contact_phone": "",
                "health_notes": "",
            },
            "enrollment": {
                "academic_year": "2026/2027",
                "stage": GradeLevel.Stage.PRIMARY,
                "grade_level": self.grade.name,
                "section": self.section.name,
                "enrollment_date": "2026-09-01",
                "usual_arrival_method": Enrollment.TransportationMethod.SCHOOL_BUS,
                "usual_departure_method": Enrollment.TransportationMethod.SCHOOL_BUS,
            },
            "resolved_references": {
                "academic_year_id": str(self.academic_year.id),
                "grade_level_id": str(self.grade.id),
                "section_id": str(self.section.id),
            },
        }

    def guardian_data(
        self,
        *,
        national_id="01234567890",
        first_name="ماهر",
        last_name="اختبار",
        phone_number="0933111222",
    ):
        return {
            "national_id": national_id,
            "first_name": first_name,
            "last_name": last_name,
            "phone_number": phone_number,
            "relationship": "أب",
        }

    def import_job(self, *, total_rows=1):
        return StudentImportJob.objects.create(
            created_by=self.actor,
            original_filename="students.xlsx",
            file_sha256="a" * 64,
            file_size=1024,
            status=StudentImportJob.Status.READY,
            total_rows=total_rows,
            valid_rows=total_rows,
        )

    def import_row(self, *, job=None, row_number=2, normalized_data=None):
        return StudentImportRow.objects.create(
            job=job or self.import_job(),
            row_number=row_number,
            normalized_data=normalized_data or self.normalized_data(),
            status=StudentImportRow.Status.READY,
        )

    def execute(self, import_row):
        return execute_student_import_row(
            import_row=import_row,
            actor=self.actor,
        )

    def assert_no_created_student_data(self):
        self.assertEqual(Student.objects.count(), 0)
        self.assertEqual(StudentHealthProfile.objects.count(), 0)
        self.assertEqual(GuardianStudent.objects.count(), 0)
        self.assertEqual(Enrollment.objects.count(), 0)
        self.assertEqual(StudentFinancialAccount.objects.count(), 0)

    def test_new_student_without_guardian_is_created_atomically(self):
        result = self.execute(self.import_row())

        self.assertEqual(Student.objects.count(), 1)
        self.assertEqual(StudentHealthProfile.objects.count(), 1)
        self.assertIsNone(result.guardian)
        self.assertFalse(result.guardian_created)
        self.assertEqual(result.enrollment.student, result.student)
        self.assertEqual(result.financial_account.enrollment, result.enrollment)

    def test_new_student_with_new_guardian_creates_link(self):
        import_row = self.import_row(
            normalized_data=self.normalized_data(guardian=self.guardian_data())
        )

        result = self.execute(import_row)

        self.assertTrue(result.guardian_created)
        self.assertEqual(result.guardian.role, User.Role.GUARDIAN)
        self.assertEqual(result.guardian.national_id, "01234567890")
        self.assertEqual(
            GuardianStudent.objects.get(student=result.student).guardian,
            result.guardian,
        )

    def test_existing_guardian_is_reused_without_password_reset(self):
        guardian = User.objects.create_user(
            username="existing-guardian",
            password="ExistingStrong!934",
            national_id="01234567890",
            role=User.Role.GUARDIAN,
            first_name="ماهر",
            last_name="اختبار",
            phone_number="0933111222",
            must_change_password=False,
        )
        original_password = guardian.password
        import_row = self.import_row(
            normalized_data=self.normalized_data(guardian=self.guardian_data())
        )

        result = self.execute(import_row)
        guardian.refresh_from_db()

        self.assertFalse(result.guardian_created)
        self.assertEqual(result.guardian, guardian)
        self.assertEqual(guardian.password, original_password)
        self.assertFalse(guardian.must_change_password)

    def test_siblings_reuse_the_same_guardian(self):
        job = self.import_job(total_rows=2)
        first_row = self.import_row(
            job=job,
            row_number=2,
            normalized_data=self.normalized_data(
                first_name="رامي",
                guardian=self.guardian_data(),
            ),
        )
        second_row = self.import_row(
            job=job,
            row_number=3,
            normalized_data=self.normalized_data(
                first_name="سامي",
                guardian=self.guardian_data(),
            ),
        )

        first = self.execute(first_row)
        second = self.execute(second_row)

        self.assertEqual(first.guardian, second.guardian)
        self.assertEqual(User.objects.filter(role=User.Role.GUARDIAN).count(), 1)

    def test_guardian_conflict_discovered_at_execution_blocks_row(self):
        import_row = self.import_row(
            normalized_data=self.normalized_data(guardian=self.guardian_data())
        )
        User.objects.create_user(
            username="conflicting-role",
            national_id="01234567890",
            role=User.Role.TEACHER,
            first_name="ماهر",
            last_name="اختبار",
        )

        with self.assertRaises(StudentImportRowExecutionError) as error:
            self.execute(import_row)

        self.assertEqual(error.exception.code, "row_revalidation_failed")
        self.assert_no_created_student_data()

    def test_new_student_suspicion_discovered_at_execution_blocks_row(self):
        import_row = self.import_row()
        Student.objects.create(
            first_name="رامي",
            last_name="اختبار",
            father_name="اسم أب مختلف",
            mother_name="اسم أم مختلف",
            birth_date=date(2018, 5, 10),
            gender=Student.Gender.MALE,
        )

        with self.assertRaises(StudentImportRowExecutionError) as error:
            self.execute(import_row)

        self.assertEqual(error.exception.code, "row_revalidation_failed")
        self.assertEqual(Student.objects.count(), 1)
        self.assertEqual(Enrollment.objects.count(), 0)

    def test_closed_year_discovered_at_execution_blocks_row(self):
        import_row = self.import_row()
        AcademicYear.objects.filter(pk=self.academic_year.pk).update(
            status=AcademicYear.Status.CLOSED
        )

        with self.assertRaises(StudentImportRowExecutionError):
            self.execute(import_row)

        self.assert_no_created_student_data()

    def test_section_change_discovered_at_execution_blocks_row(self):
        import_row = self.import_row()
        other_year = AcademicYear.objects.create(
            start_date=date(2027, 9, 1),
            end_date=date(2028, 6, 30),
            status=AcademicYear.Status.DRAFT,
        )
        Section.objects.filter(pk=self.section.pk).update(academic_year=other_year)

        with self.assertRaises(StudentImportRowExecutionError):
            self.execute(import_row)

        self.assert_no_created_student_data()

    def test_health_profile_failure_rolls_back_student(self):
        with patch(
            "students.services.ensure_student_health_profile",
            side_effect=RuntimeError("simulated health failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.execute(self.import_row())

        self.assert_no_created_student_data()

    def test_enrollment_failure_rolls_back_student_and_new_guardian(self):
        import_row = self.import_row(
            normalized_data=self.normalized_data(guardian=self.guardian_data())
        )
        users_before = User.objects.count()

        with patch(
            "students.student_import_row_execution.EnrollmentSerializer.save",
            side_effect=RuntimeError("simulated enrollment failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.execute(import_row)

        self.assert_no_created_student_data()
        self.assertEqual(User.objects.count(), users_before)

    def test_financial_account_failure_rolls_back_complete_row(self):
        import_row = self.import_row(
            normalized_data=self.normalized_data(guardian=self.guardian_data())
        )
        users_before = User.objects.count()

        with patch(
            "students.student_import_row_execution.ensure_financial_account_for_enrollment",
            side_effect=RuntimeError("simulated finance failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.execute(import_row)

        self.assert_no_created_student_data()
        self.assertEqual(User.objects.count(), users_before)

    def test_result_never_contains_plaintext_password(self):
        import_row = self.import_row(
            normalized_data=self.normalized_data(guardian=self.guardian_data())
        )

        result = self.execute(import_row)
        payload = result.to_dict()

        self.assertNotIn("password", str(payload).casefold())
        self.assertEqual(
            set(payload),
            {
                "student_id",
                "health_profile_id",
                "guardian_id",
                "guardian_created",
                "enrollment_id",
                "financial_account_id",
            },
        )
