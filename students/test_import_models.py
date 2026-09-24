from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from students.models import StudentImportJob, StudentImportRow


User = get_user_model()


class StudentImportModelsTests(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="student-import-creator",
            role=User.Role.SCHOOL_ADMIN,
        )

    def create_job(self, **overrides):
        values = {
            "created_by": self.creator,
            "original_filename": "students.xlsx",
            "file_sha256": "a" * 64,
            "file_size": 1024,
        }
        values.update(overrides)
        return StudentImportJob.objects.create(**values)

    def test_job_and_row_can_be_created(self):
        job = self.create_job()
        row = StudentImportRow.objects.create(
            job=job,
            row_number=2,
            normalized_data={"first_name": "Ahmad"},
        )

        self.assertEqual(row.job, job)
        self.assertEqual(row.normalized_data, {"first_name": "Ahmad"})

    def test_defaults(self):
        job = self.create_job()
        row = StudentImportRow.objects.create(job=job, row_number=2)

        self.assertEqual(job.status, StudentImportJob.Status.PENDING)
        self.assertEqual(job.total_rows, 0)
        self.assertEqual(job.valid_rows, 0)
        self.assertEqual(job.invalid_rows, 0)
        self.assertEqual(job.review_rows, 0)
        self.assertEqual(job.processed_rows, 0)
        self.assertEqual(job.succeeded_rows, 0)
        self.assertEqual(job.failed_rows, 0)
        self.assertEqual(job.batch_size, 100)
        self.assertEqual(row.status, StudentImportRow.Status.PENDING)
        self.assertEqual(row.normalized_data, {})
        self.assertEqual(row.validation_errors, [])
        self.assertEqual(row.attempt_count, 0)
        self.assertIsNone(row.lease_token)
        self.assertIsNone(row.lease_expires_at)

    def test_review_and_terminal_statuses_are_available(self):
        self.assertEqual(
            StudentImportJob.Status.VALIDATION_FAILED,
            "validation_failed",
        )
        self.assertEqual(
            StudentImportJob.Status.COMPLETED_WITH_ERRORS,
            "completed_with_errors",
        )
        self.assertEqual(
            StudentImportRow.Status.REVIEW_REQUIRED,
            "review_required",
        )
        self.assertEqual(StudentImportRow.Status.READY, "ready")

    def test_row_number_must_be_unique_within_job(self):
        job = self.create_job()
        StudentImportRow.objects.create(job=job, row_number=2)

        with self.assertRaises(IntegrityError), transaction.atomic():
            StudentImportRow.objects.create(job=job, row_number=2)

    def test_same_row_number_is_allowed_in_another_job(self):
        first_job = self.create_job(file_sha256="a" * 64)
        second_job = self.create_job(file_sha256="b" * 64)

        StudentImportRow.objects.create(job=first_job, row_number=2)
        other_row = StudentImportRow.objects.create(job=second_job, row_number=2)

        self.assertEqual(other_row.row_number, 2)

    def test_job_numeric_constraints(self):
        constrained_fields = (
            "file_size",
            "total_rows",
            "valid_rows",
            "invalid_rows",
            "review_rows",
            "processed_rows",
            "succeeded_rows",
            "failed_rows",
        )

        for field_name in constrained_fields:
            with self.subTest(field=field_name):
                job = self.create_job(file_sha256=field_name.ljust(64, "x"))
                with self.assertRaises(IntegrityError), transaction.atomic():
                    StudentImportJob.objects.filter(pk=job.pk).update(
                        **{field_name: -1}
                    )

        for invalid_batch_size in (0, 101):
            with self.subTest(batch_size=invalid_batch_size):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    self.create_job(
                        file_sha256=str(invalid_batch_size).ljust(64, "x"),
                        batch_size=invalid_batch_size,
                    )

    def test_row_numeric_constraints(self):
        job = self.create_job()

        with self.assertRaises(IntegrityError), transaction.atomic():
            StudentImportRow.objects.create(job=job, row_number=0)

        row = StudentImportRow.objects.create(job=job, row_number=2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudentImportRow.objects.filter(pk=row.pk).update(attempt_count=-1)
