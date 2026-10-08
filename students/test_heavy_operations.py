from datetime import date
from io import BytesIO

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from academics.models import AcademicYear, GradeLevel, Section
from students.models import GuardianStudent, Student, StudentImportJob, StudentImportRow
from students.services import register_student
from students.student_import_batch_service import process_next_batch
from students.student_import_excel import MAX_FILE_SIZE_BYTES
from students.student_import_job_service import create_student_import_job
from students.test_student_import_batch_service import StudentImportBatchTestMixin
from students.test_student_import_job_service import student_row, xlsx_file


User = get_user_model()

LEADING_ZERO_NATIONAL_ID = "00123456789"


def user_table_selects(queries):
    marker = f'FROM "{User._meta.db_table}"'
    return [
        q for q in queries
        if q["sql"].lstrip().upper().startswith("SELECT") and marker in q["sql"]
    ]


class StudentImportJobScalingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.creator = User.objects.create_user(username="heavy-import-creator", role=User.Role.SCHOOL_ADMIN)
        cls.academic_year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1), end_date=date(2027, 6, 30), status=AcademicYear.Status.ACTIVE,
        )
        cls.grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="الصف الثالث")
        Section.objects.create(academic_year=cls.academic_year, grade_level=cls.grade, name="أ")

    def sibling_rows(self, count):
        """Distinct students sharing one new guardian whose national ID starts with zeros."""
        return [
            student_row(**{
                "الاسم الأول بالعربية *": f"طالب{index}",
                "الرقم الوطني لولي الأمر": LEADING_ZERO_NATIONAL_ID,
                "اسم ولي الأمر الأول": "ماهر",
                "كنية ولي الأمر": "اختبار",
                "رقم هاتف ولي الأمر": "0933111222",
                "صلة القرابة": "أب",
            })
            for index in range(count)
        ]

    def create_job(self, rows):
        with CaptureQueriesContext(connection) as ctx:
            result = create_student_import_job(uploaded_file=xlsx_file(*rows), created_by=self.creator)
        self.assertTrue(result.created, result.file_errors)
        return result.job, ctx.captured_queries

    def test_validation_and_persistence_queries_do_not_grow_with_rows(self):
        small_job, small = self.create_job(self.sibling_rows(3))
        large_job, large = self.create_job(self.sibling_rows(12))

        self.assertEqual(len(large), len(small))
        self.assertEqual(small_job.status, StudentImportJob.Status.READY)
        self.assertEqual(large_job.status, StudentImportJob.Status.READY)
        self.assertEqual(large_job.rows.count(), 12)
        self.assertEqual(
            [row.row_number for row in large_job.rows.order_by("row_number")],
            list(range(2, 14)),
        )
        national_ids = {
            row.normalized_data["guardian"]["national_id"] for row in large_job.rows.all()
        }
        self.assertEqual(national_ids, {LEADING_ZERO_NATIONAL_ID})

    def test_oversized_upload_is_rejected_without_a_job(self):
        oversized = BytesIO(b"x" * (MAX_FILE_SIZE_BYTES + 1))
        oversized.name = "students.xlsx"

        result = create_student_import_job(uploaded_file=oversized, created_by=self.creator)

        self.assertFalse(result.created)
        self.assertEqual([error.code for error in result.file_errors], ["file_too_large"])
        self.assertFalse(StudentImportJob.objects.exists())

    def test_invalid_row_keeps_row_number_and_creates_no_school_data(self):
        result = create_student_import_job(
            uploaded_file=xlsx_file(student_row(), student_row(**{"الجنس *": "غير معروف"})),
            created_by=self.creator,
        )

        job = result.job
        self.assertEqual(job.status, StudentImportJob.Status.VALIDATION_FAILED)
        invalid = job.rows.get(status=StudentImportRow.Status.INVALID)
        self.assertEqual(invalid.row_number, 3)
        self.assertTrue(invalid.validation_errors)
        self.assertFalse(Student.objects.exists())


class StudentImportExecutionScalingTests(StudentImportBatchTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_reference_data()

    def guardian(self):
        return {
            "national_id": LEADING_ZERO_NATIONAL_ID,
            "first_name": "ماهر",
            "last_name": "اختبار",
            "phone_number": "0933111222",
            "relationship": "أب",
        }

    def job_with_guardian(self, row_count):
        job = self.make_job(row_count=row_count)
        for row in job.rows.all():
            row.normalized_data = dict(row.normalized_data, guardian=self.guardian())
            row.save(update_fields=["normalized_data"])
        return job

    def batch_queries(self, row_count):
        job = self.make_job(row_count=row_count)
        # Unique names per job so earlier jobs never look like possible duplicates.
        for row in job.rows.all():
            student = dict(row.normalized_data["student"], first_name=f"دفعة{job.pk.hex[:8]}-{row.row_number}")
            row.normalized_data = dict(row.normalized_data, student=student)
            row.save(update_fields=["normalized_data"])
        with CaptureQueriesContext(connection) as ctx:
            result = process_next_batch(job=job, actor=self.actor)
        self.assertEqual(result.job.status, StudentImportJob.Status.COMPLETED)
        return len(ctx.captured_queries)

    def test_each_extra_row_costs_the_same_constant_number_of_queries(self):
        # Rows are written one by one on purpose (save(), signals, per-row
        # savepoints and revalidation); the cost per row must stay constant.
        self.batch_queries(1)  # warm per-process caches (e.g. content types)
        one, two, three = (self.batch_queries(count) for count in (1, 2, 3))
        self.assertEqual(three - two, two - one)

    def test_shared_new_guardian_is_created_once_with_string_national_id(self):
        result = process_next_batch(job=self.job_with_guardian(3), actor=self.actor)

        self.assertEqual(result.job.status, StudentImportJob.Status.COMPLETED)
        guardian = User.objects.get(national_id=LEADING_ZERO_NATIONAL_ID)
        self.assertEqual(guardian.username, LEADING_ZERO_NATIONAL_ID)
        self.assertTrue(guardian.must_change_password)
        self.assertEqual(GuardianStudent.objects.filter(guardian=guardian).count(), 3)
        self.assertEqual(User.objects.filter(role=User.Role.GUARDIAN).count(), 1)

    def test_existing_guardian_keeps_password_and_token_version(self):
        existing = User.objects.create_user(
            username="heavy-existing-guardian", national_id=LEADING_ZERO_NATIONAL_ID,
            password="ExistingStrong!934", role=User.Role.GUARDIAN,
            first_name="ماهر", last_name="اختبار", phone_number="0933111222",
            must_change_password=False,
        )
        password, token_version = existing.password, existing.token_version

        result = process_next_batch(job=self.job_with_guardian(2), actor=self.actor)

        self.assertEqual(result.job.status, StudentImportJob.Status.COMPLETED)
        existing.refresh_from_db()
        self.assertEqual((existing.password, existing.token_version), (password, token_version))
        self.assertFalse(existing.must_change_password)
        self.assertEqual(User.objects.filter(national_id=LEADING_ZERO_NATIONAL_ID).count(), 1)


class RegistrationQueryShapeTests(TestCase):
    student_data = {
        "first_name": "سارة", "last_name": "علي",
        "birth_date": date(2018, 2, 1), "gender": Student.Gender.FEMALE,
    }
    guardian_data = {
        "national_id": LEADING_ZERO_NATIONAL_ID, "first_name": "أحمد",
        "last_name": "علي", "phone_number": "0999999999", "relationship": "أب",
    }

    def register(self):
        with CaptureQueriesContext(connection) as ctx:
            result = register_student(student_data=dict(self.student_data), guardian_data=dict(self.guardian_data))
        return result, ctx.captured_queries

    def test_existing_guardian_is_looked_up_once(self):
        User.objects.create_user(
            username="registration-existing", national_id=LEADING_ZERO_NATIONAL_ID,
            role=User.Role.GUARDIAN, must_change_password=False,
        )
        result, queries = self.register()

        self.assertEqual(result["guardian_account"]["status"], "linked_existing")
        self.assertEqual(len(user_table_selects(queries)), 1)

    def test_new_guardian_needs_only_identity_and_username_checks(self):
        result, queries = self.register()

        self.assertEqual(result["guardian_account"]["status"], "created")
        self.assertEqual(result["guardian_account"]["username"], LEADING_ZERO_NATIONAL_ID)
        self.assertEqual(len(user_table_selects(queries)), 2)
