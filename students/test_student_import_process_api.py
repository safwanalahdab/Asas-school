from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, Section
from students.models import Enrollment, Student, StudentImportJob, StudentImportRow


User = get_user_model()


class StudentImportProcessApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username="student-import-process-owner",
            role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
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

    def setUp(self):
        self.client = APIClient()

    def authenticate(self, role):
        user = User.objects.create_user(
            username=f"student-import-process-{role}-{User.objects.count()}",
            role=role,
            must_change_password=False,
        )
        self.client.force_authenticate(user, token={"client": "web"})
        return user

    def normalized_data(self, first_name="رامي"):
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
            "guardian": None,
            "health_profile": {},
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

    def make_job(
        self,
        *,
        job_status=StudentImportJob.Status.READY,
        row_status=StudentImportRow.Status.READY,
    ):
        job = StudentImportJob.objects.create(
            created_by=self.owner,
            original_filename="students.xlsx",
            file_sha256="a" * 64,
            file_size=1024,
            status=job_status,
            total_rows=1,
            valid_rows=(
                0
                if row_status
                in {
                    StudentImportRow.Status.INVALID,
                    StudentImportRow.Status.REVIEW_REQUIRED,
                }
                else 1
            ),
            invalid_rows=1 if row_status == StudentImportRow.Status.INVALID else 0,
            review_rows=(
                1 if row_status == StudentImportRow.Status.REVIEW_REQUIRED else 0
            ),
        )
        StudentImportRow.objects.create(
            job=job,
            row_number=2,
            normalized_data=self.normalized_data(),
            status=row_status,
        )
        return job

    @staticmethod
    def process_url(job):
        return f"/api/v1/students/imports/{job.pk}/process/"

    def test_admin_can_process_ready_job(self):
        job = self.make_job()
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.post(self.process_url(job), {}, format="json")

        self.assertEqual(response.status_code, 200)

    def test_secretariat_can_process_ready_job(self):
        job = self.make_job()
        self.authenticate(User.Role.SECRETARIAT)

        response = self.client.post(self.process_url(job), {}, format="json")

        self.assertEqual(response.status_code, 200)

    def test_superuser_can_process_ready_job(self):
        job = self.make_job()
        user = User.objects.create_superuser(
            username="student-import-process-root",
            password="Strong!934",
        )
        self.client.force_authenticate(user, token={"client": "web"})

        response = self.client.post(self.process_url(job), {}, format="json")

        self.assertEqual(response.status_code, 200)

    def test_unauthorized_roles_are_denied(self):
        for role in (
            User.Role.SUPERVISOR,
            User.Role.TEACHER,
            User.Role.ACCOUNTANT,
            User.Role.GUARDIAN,
            User.Role.TECH_SUPPORT,
        ):
            with self.subTest(role=role):
                job = self.make_job()
                self.authenticate(role)
                response = self.client.post(self.process_url(job), {}, format="json")
                self.assertEqual(response.status_code, 403)
                job.refresh_from_db()
                self.assertEqual(job.status, StudentImportJob.Status.READY)

    def test_unauthenticated_request_is_denied(self):
        job = self.make_job()

        response = self.client.post(self.process_url(job), {}, format="json")

        self.assertEqual(response.status_code, 401)

    def test_nonexistent_job_returns_404(self):
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.post(
            "/api/v1/students/imports/"
            "00000000-0000-0000-0000-000000000000/process/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 404)

    def test_ready_job_creates_student_and_enrollment(self):
        job = self.make_job()
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.post(self.process_url(job), {}, format="json")

        self.assertEqual(response.status_code, 200)
        row = job.rows.get()
        self.assertEqual(row.status, StudentImportRow.Status.SUCCEEDED)
        self.assertIsNotNone(row.student_id)
        self.assertIsNotNone(row.enrollment_id)
        self.assertEqual(Student.objects.count(), 1)
        self.assertEqual(Enrollment.objects.count(), 1)

    def test_response_contains_updated_progress_and_batch_summary(self):
        job = self.make_job()
        self.authenticate(User.Role.SECRETARIAT)

        response = self.client.post(self.process_url(job), {}, format="json")

        data = response.data["data"]
        self.assertEqual(data["status"], StudentImportJob.Status.COMPLETED)
        self.assertEqual(data["total_rows"], 1)
        self.assertEqual(data["ready_rows"], 1)
        self.assertEqual(data["succeeded_rows"], 1)
        self.assertEqual(data["failed_rows"], 0)
        self.assertEqual(
            data["batch"],
            {"claimed_rows": 1, "succeeded_rows": 1, "failed_rows": 0},
        )

    def test_processing_job_continues_through_batch_service(self):
        job = self.make_job(job_status=StudentImportJob.Status.PROCESSING)
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.post(self.process_url(job), {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], StudentImportJob.Status.COMPLETED)
        self.assertEqual(Student.objects.count(), 1)

    def test_validation_failed_job_does_not_start(self):
        job = self.make_job(
            job_status=StudentImportJob.Status.VALIDATION_FAILED,
            row_status=StudentImportRow.Status.INVALID,
        )
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.post(self.process_url(job), {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "JOB_NOT_PROCESSABLE")
        self.assertFalse(Student.objects.exists())

    def test_completed_job_is_not_reprocessed(self):
        job = self.make_job(
            job_status=StudentImportJob.Status.COMPLETED,
            row_status=StudentImportRow.Status.SUCCEEDED,
        )
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.post(self.process_url(job), {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["batch"]["claimed_rows"], 0)
        self.assertFalse(Student.objects.exists())

    def test_completed_with_errors_job_is_not_reprocessed(self):
        job = self.make_job(
            job_status=StudentImportJob.Status.COMPLETED_WITH_ERRORS,
            row_status=StudentImportRow.Status.FAILED,
        )
        self.authenticate(User.Role.SECRETARIAT)

        response = self.client.post(self.process_url(job), {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["batch"]["claimed_rows"], 0)
        self.assertFalse(Student.objects.exists())

    def test_repeated_process_call_does_not_duplicate_student(self):
        job = self.make_job()
        self.authenticate(User.Role.SCHOOL_ADMIN)

        first = self.client.post(self.process_url(job), {}, format="json")
        second = self.client.post(self.process_url(job), {}, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(Student.objects.count(), 1)
        self.assertEqual(Enrollment.objects.count(), 1)
        self.assertEqual(second.data["data"]["batch"]["claimed_rows"], 0)

    def test_response_does_not_expose_internal_or_sensitive_fields(self):
        job = self.make_job()
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.post(self.process_url(job), {}, format="json")

        self.assertEqual(
            set(response.data["data"]),
            {
                "id",
                "status",
                "total_rows",
                "ready_rows",
                "invalid_rows",
                "review_required_rows",
                "succeeded_rows",
                "failed_rows",
                "created_at",
                "batch",
            },
        )
        self.assertEqual(
            set(response.data["data"]["batch"]),
            {"claimed_rows", "succeeded_rows", "failed_rows"},
        )
