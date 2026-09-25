from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from students.models import StudentImportJob, StudentImportRow


User = get_user_model()


class StudentImportReadApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username="student-import-owner",
            role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
        )

    def setUp(self):
        self.client = APIClient()

    def authenticate(self, role):
        user = User.objects.create_user(
            username=f"student-import-read-{role}-{User.objects.count()}",
            role=role,
            must_change_password=False,
        )
        self.client.force_authenticate(user, token={"client": "web"})
        return user

    def make_job(self, *, status=StudentImportJob.Status.VALIDATION_FAILED):
        return StudentImportJob.objects.create(
            created_by=self.owner,
            original_filename="students.xlsx",
            file_sha256="a" * 64,
            file_size=1024,
            status=status,
            total_rows=3,
            valid_rows=1,
            invalid_rows=1,
            review_rows=1,
            succeeded_rows=0,
            failed_rows=0,
        )

    @staticmethod
    def make_row(job, row_number, status, validation_errors=None):
        return StudentImportRow.objects.create(
            job=job,
            row_number=row_number,
            normalized_data={
                "student": {
                    "first_name": "اسم",
                    "last_name": "اختبار",
                }
            },
            status=status,
            validation_errors=validation_errors or [],
        )

    @staticmethod
    def detail_url(job):
        return f"/api/v1/students/imports/{job.pk}/"

    @staticmethod
    def rows_url(job):
        return f"/api/v1/students/imports/{job.pk}/rows/"

    def test_admin_can_retrieve_job_details(self):
        job = self.make_job()
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.get(self.detail_url(job))

        self.assertEqual(response.status_code, 200)

    def test_secretariat_can_retrieve_job_details(self):
        job = self.make_job()
        self.authenticate(User.Role.SECRETARIAT)

        response = self.client.get(self.detail_url(job))

        self.assertEqual(response.status_code, 200)

    def test_superuser_can_retrieve_job_and_rows(self):
        job = self.make_job()
        self.make_row(job, 2, StudentImportRow.Status.READY)
        user = User.objects.create_superuser(
            username="student-import-read-root",
            password="Strong!934",
        )
        self.client.force_authenticate(user, token={"client": "web"})

        detail_response = self.client.get(self.detail_url(job))
        rows_response = self.client.get(self.rows_url(job))

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(rows_response.status_code, 200)

    def test_unauthorized_role_cannot_retrieve_job_details(self):
        job = self.make_job()
        for role in (
            User.Role.SUPERVISOR,
            User.Role.TEACHER,
            User.Role.GUARDIAN,
            User.Role.TECH_SUPPORT,
        ):
            with self.subTest(role=role):
                self.authenticate(role)
                self.assertEqual(self.client.get(self.detail_url(job)).status_code, 403)

    def test_unauthenticated_user_cannot_retrieve_job_details(self):
        job = self.make_job()

        response = self.client.get(self.detail_url(job))

        self.assertEqual(response.status_code, 401)

    def test_existing_job_returns_correct_safe_summary(self):
        job = self.make_job()
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.get(self.detail_url(job))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["data"],
            {
                "id": str(job.id),
                "status": StudentImportJob.Status.VALIDATION_FAILED,
                "total_rows": 3,
                "ready_rows": 1,
                "invalid_rows": 1,
                "review_required_rows": 1,
                "succeeded_rows": 0,
                "failed_rows": 0,
                "created_at": response.data["data"]["created_at"],
            },
        )

    def test_nonexistent_job_returns_404(self):
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.get(
            "/api/v1/students/imports/00000000-0000-0000-0000-000000000000/"
        )

        self.assertEqual(response.status_code, 404)

    def test_job_details_do_not_expose_internal_fields_or_rows(self):
        job = self.make_job()
        self.make_row(job, 2, StudentImportRow.Status.INVALID)
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.get(self.detail_url(job))

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
            },
        )

    def test_admin_and_secretariat_can_list_rows(self):
        job = self.make_job()
        self.make_row(job, 2, StudentImportRow.Status.INVALID)

        for role in (User.Role.SCHOOL_ADMIN, User.Role.SECRETARIAT):
            with self.subTest(role=role):
                self.authenticate(role)
                response = self.client.get(self.rows_url(job))
                self.assertEqual(response.status_code, 200)

    def test_unauthorized_role_cannot_list_rows(self):
        job = self.make_job()
        self.make_row(job, 2, StudentImportRow.Status.INVALID)
        self.authenticate(User.Role.SUPERVISOR)

        response = self.client.get(self.rows_url(job))

        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_user_cannot_list_rows(self):
        job = self.make_job()

        response = self.client.get(self.rows_url(job))

        self.assertEqual(response.status_code, 401)

    def test_rows_for_nonexistent_job_return_404(self):
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.get(
            "/api/v1/students/imports/"
            "00000000-0000-0000-0000-000000000000/rows/"
        )

        self.assertEqual(response.status_code, 404)

    def test_rows_belong_only_to_requested_job(self):
        job = self.make_job()
        other_job = self.make_job()
        expected = self.make_row(job, 2, StudentImportRow.Status.INVALID)
        self.make_row(other_job, 2, StudentImportRow.Status.INVALID)
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.get(self.rows_url(job))

        results = response.data["data"]["results"]
        self.assertEqual([item["id"] for item in results], [str(expected.id)])

    def test_rows_are_paginated_with_project_pagination(self):
        job = self.make_job()
        for index in range(55):
            self.make_row(
                job,
                index + 2,
                StudentImportRow.Status.INVALID,
            )
        self.authenticate(User.Role.SECRETARIAT)

        response = self.client.get(self.rows_url(job))

        page = response.data["data"]
        self.assertEqual(page["count"], 55)
        self.assertEqual(len(page["results"]), 20)
        self.assertIsNotNone(page["next"])

    def test_rows_can_be_filtered_by_status(self):
        job = self.make_job()
        invalid = self.make_row(job, 2, StudentImportRow.Status.INVALID)
        self.make_row(job, 3, StudentImportRow.Status.REVIEW_REQUIRED)
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.get(
            self.rows_url(job),
            {"status": StudentImportRow.Status.INVALID},
        )

        results = response.data["data"]["results"]
        self.assertEqual([item["id"] for item in results], [str(invalid.id)])

    def test_invalid_status_filter_returns_validation_error(self):
        job = self.make_job()
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.get(self.rows_url(job), {"status": "unknown"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.data["errors"])

    def test_validation_errors_are_returned(self):
        job = self.make_job()
        errors = [
            {
                "code": "required",
                "detail": "هذا الحقل مطلوب.",
                "field": "first_name",
                "excel_row_number": 2,
            }
        ]
        self.make_row(
            job,
            2,
            StudentImportRow.Status.INVALID,
            validation_errors=errors,
        )
        self.authenticate(User.Role.SECRETARIAT)

        response = self.client.get(self.rows_url(job))

        self.assertEqual(response.data["data"]["results"][0]["validation_errors"], errors)

    def test_row_response_does_not_expose_internal_or_sensitive_fields(self):
        job = self.make_job()
        self.make_row(job, 2, StudentImportRow.Status.PROCESSING)
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.get(self.rows_url(job))

        self.assertEqual(
            set(response.data["data"]["results"][0]),
            {"id", "row_number", "status", "validation_errors"},
        )
