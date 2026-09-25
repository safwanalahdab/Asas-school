from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from threading import Event
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from academics.models import AcademicYear, GradeLevel, Section
from finance.models import GradeTuitionPlan
from students.models import Enrollment, Student, StudentImportJob, StudentImportRow
from students.student_import_batch_service import (
    DEFAULT_BATCH_SIZE,
    MAX_BATCH_SIZE,
    StudentImportBatchError,
    _claim_rows,
    _execute_claimed_row,
    _refresh_job,
    process_next_batch,
)
from students.student_import_row_execution import StudentImportRowExecutionError


User = get_user_model()


class StudentImportBatchTestMixin:
    @classmethod
    def create_reference_data(cls):
        cls.actor = User.objects.create_user(
            username="student-import-batch-executor",
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
        GradeTuitionPlan.objects.create(
            academic_year=cls.academic_year,
            grade_level=cls.grade,
            base_tuition_usd=Decimal("500.00"),
            created_by=cls.actor,
        )

    def normalized_data(self, first_name):
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

    def make_job(self, row_count=1, status=StudentImportJob.Status.READY):
        job = StudentImportJob.objects.create(
            created_by=self.actor,
            original_filename="students.xlsx",
            file_sha256="a" * 64,
            file_size=1024,
            status=status,
            total_rows=row_count,
            valid_rows=row_count,
        )
        rows = [
            StudentImportRow(
                job=job,
                row_number=index + 2,
                normalized_data=self.normalized_data(f"طالب{index}"),
                status=StudentImportRow.Status.READY,
            )
            for index in range(row_count)
        ]
        StudentImportRow.objects.bulk_create(rows)
        return job


class StudentImportBatchServiceTests(StudentImportBatchTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_reference_data()

    def test_successful_batch_persists_references_and_completes_job(self):
        job = self.make_job(row_count=2)

        result = process_next_batch(job=job, actor=self.actor)

        self.assertEqual(result.claimed_rows, 2)
        self.assertEqual(result.job.status, StudentImportJob.Status.COMPLETED)
        self.assertEqual(result.job.processed_rows, 2)
        self.assertEqual(result.job.succeeded_rows, 2)
        self.assertEqual(result.job.failed_rows, 0)
        for row in job.rows.all():
            self.assertEqual(row.status, StudentImportRow.Status.SUCCEEDED)
            self.assertIsNotNone(row.student_id)
            self.assertIsNotNone(row.enrollment_id)
            self.assertIsNotNone(row.processed_at)
            self.assertIsNone(row.lease_token)

    def test_default_batch_size_is_ten_and_maximum_is_one_hundred(self):
        self.assertEqual(DEFAULT_BATCH_SIZE, 10)
        self.assertEqual(MAX_BATCH_SIZE, 100)
        job = self.make_job(row_count=11)

        _, claims = _claim_rows(job_id=job.pk, batch_size=DEFAULT_BATCH_SIZE)

        self.assertEqual(len(claims), 10)

    def test_invalid_batch_sizes_are_rejected(self):
        job = self.make_job()
        for invalid_size in (True, 0, -1, 101, 1.5, "10", None):
            with self.subTest(batch_size=invalid_size):
                with self.assertRaises(StudentImportBatchError) as error:
                    process_next_batch(
                        job=job,
                        actor=self.actor,
                        batch_size=invalid_size,
                    )
                self.assertEqual(error.exception.code, "invalid_batch_size")

    def test_batch_size_one_hundred_is_accepted(self):
        job = self.make_job()

        result = process_next_batch(
            job=job,
            actor=self.actor,
            batch_size=100,
        )

        self.assertEqual(result.claimed_rows, 1)
        self.assertEqual(result.job.batch_size, 100)

    def test_validation_failed_job_cannot_start(self):
        job = self.make_job(
            status=StudentImportJob.Status.VALIDATION_FAILED,
        )
        job.rows.update(status=StudentImportRow.Status.INVALID)

        with self.assertRaises(StudentImportBatchError) as error:
            process_next_batch(job=job, actor=self.actor)

        self.assertEqual(error.exception.code, "job_not_processable")
        job.refresh_from_db()
        self.assertEqual(job.status, StudentImportJob.Status.VALIDATION_FAILED)

    def test_ready_job_must_still_contain_only_ready_rows(self):
        job = self.make_job(row_count=2)
        job.rows.filter(row_number=2).update(
            status=StudentImportRow.Status.REVIEW_REQUIRED
        )

        with self.assertRaises(StudentImportBatchError):
            process_next_batch(job=job, actor=self.actor)

        job.refresh_from_db()
        self.assertEqual(job.status, StudentImportJob.Status.READY)

    def test_completed_job_is_idempotent_and_not_reopened(self):
        job = self.make_job()
        first = process_next_batch(job=job, actor=self.actor)
        student_id = first.job.rows.get().student_id

        second = process_next_batch(job=job, actor=self.actor)

        self.assertEqual(second.claimed_rows, 0)
        self.assertEqual(second.job.status, StudentImportJob.Status.COMPLETED)
        self.assertEqual(second.job.processed_rows, 1)
        self.assertEqual(second.job.succeeded_rows, 1)
        self.assertEqual(second.job.failed_rows, 0)
        self.assertEqual(Student.objects.count(), 1)
        self.assertEqual(second.job.rows.get().student_id, student_id)

    def test_expected_row_failure_is_recorded_and_next_row_continues(self):
        job = self.make_job(row_count=2)
        first_row = job.rows.get(row_number=2)
        Student.objects.create(
            first_name="طالب0",
            last_name="اختبار",
            father_name="اسم مختلف",
            mother_name="اسم مختلف",
            birth_date=date(2018, 5, 10),
            gender=Student.Gender.MALE,
        )

        result = process_next_batch(job=job, actor=self.actor)

        first_row.refresh_from_db()
        self.assertEqual(first_row.status, StudentImportRow.Status.FAILED)
        self.assertEqual(first_row.validation_errors[0]["code"], "row_revalidation_failed")
        self.assertEqual(result.job.status, StudentImportJob.Status.COMPLETED_WITH_ERRORS)
        self.assertEqual(result.job.processed_rows, 2)
        self.assertEqual(result.job.succeeded_rows, 1)
        self.assertEqual(result.job.failed_rows, 1)

    def test_structural_failure_stops_batch_and_keeps_prior_success(self):
        job = self.make_job(row_count=2)
        from students import student_import_batch_service as service

        real_create = service._create_student_for_import_row
        calls = 0

        def create_then_crash(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("simulated database outage")
            return real_create(**kwargs)

        with patch.object(
            service,
            "_create_student_for_import_row",
            side_effect=create_then_crash,
        ):
            with self.assertRaises(RuntimeError):
                process_next_batch(job=job, actor=self.actor)

        rows = list(job.rows.order_by("row_number"))
        job.refresh_from_db()
        self.assertEqual(rows[0].status, StudentImportRow.Status.SUCCEEDED)
        self.assertEqual(rows[1].status, StudentImportRow.Status.PROCESSING)
        self.assertEqual(job.processed_rows, 1)
        self.assertEqual(job.succeeded_rows, 1)
        self.assertEqual(Student.objects.count(), 1)

    def test_expired_processing_row_is_reclaimed(self):
        job = self.make_job()
        row = job.rows.get()
        old_token = row.lease_token
        row.status = StudentImportRow.Status.PROCESSING
        row.lease_token = old_token or "00000000-0000-0000-0000-000000000001"
        row.lease_expires_at = timezone.now() - timedelta(seconds=1)
        row.attempt_count = 1
        row.save()
        job.status = StudentImportJob.Status.PROCESSING
        job.started_at = timezone.now() - timedelta(minutes=20)
        job.save()

        result = process_next_batch(job=job, actor=self.actor)

        row.refresh_from_db()
        self.assertEqual(result.job.status, StudentImportJob.Status.COMPLETED)
        self.assertEqual(row.status, StudentImportRow.Status.SUCCEEDED)
        self.assertEqual(row.attempt_count, 2)

    def test_stale_worker_cannot_commit_after_lease_is_reclaimed(self):
        job = self.make_job()
        _, first_claims = _claim_rows(job_id=job.pk, batch_size=1)
        row = job.rows.get()
        row.lease_expires_at = timezone.now() - timedelta(seconds=1)
        row.save(update_fields=["lease_expires_at"])
        _, second_claims = _claim_rows(job_id=job.pk, batch_size=1)

        stale_result = _execute_claimed_row(
            claim=first_claims[0],
            actor=self.actor,
        )

        self.assertEqual(stale_result.status, "lease_lost")
        self.assertEqual(Student.objects.count(), 0)
        self.assertNotEqual(first_claims[0].lease_token, second_claims[0].lease_token)

    def test_job_is_not_finished_while_a_row_is_processing(self):
        job = self.make_job(row_count=2)
        job.status = StudentImportJob.Status.PROCESSING
        job.save(update_fields=["status"])
        job.rows.filter(row_number=2).update(status=StudentImportRow.Status.SUCCEEDED)
        job.rows.filter(row_number=3).update(status=StudentImportRow.Status.PROCESSING)

        refreshed = _refresh_job(job.pk)

        self.assertEqual(refreshed.status, StudentImportJob.Status.PROCESSING)
        self.assertEqual(refreshed.processed_rows, 1)

    def test_expected_failure_rolls_back_created_records_before_marking_failed(self):
        job = self.make_job()
        from students import student_import_batch_service as service

        def create_then_fail(*, persisted_row, actor):
            Student.objects.create(
                first_name="لن يبقى",
                last_name="اختبار",
                birth_date=date(2018, 5, 10),
                gender=Student.Gender.MALE,
            )
            raise StudentImportRowExecutionError(
                code="safe_row_failure",
                detail="تعذر تنفيذ الصف.",
            )

        with patch.object(
            service,
            "_create_student_for_import_row",
            side_effect=create_then_fail,
        ):
            result = process_next_batch(job=job, actor=self.actor)

        row = job.rows.get()
        self.assertEqual(result.job.status, StudentImportJob.Status.COMPLETED_WITH_ERRORS)
        self.assertEqual(row.status, StudentImportRow.Status.FAILED)
        self.assertEqual(Student.objects.count(), 0)


@skipUnless(connection.vendor == "postgresql", "يتطلب PostgreSQL حقيقيًا")
class StudentImportBatchPostgreSQLConcurrencyTests(
    StudentImportBatchTestMixin,
    TransactionTestCase,
):
    reset_sequences = True

    def setUp(self):
        super().setUp()
        self.create_reference_data()

    def test_concurrent_claims_never_own_the_same_rows(self):
        job = self.make_job(row_count=4)

        def claim_two_rows():
            connections.close_all()
            try:
                _, claims = _claim_rows(job_id=job.pk, batch_size=2)
                return {claim.row_id for claim in claims}
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(claim_two_rows)
            second_future = executor.submit(claim_two_rows)
            first = first_future.result(timeout=10)
            second = second_future.result(timeout=10)

        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 2)
        self.assertTrue(first.isdisjoint(second))
        self.assertEqual(first | second, set(job.rows.values_list("id", flat=True)))

    def test_lease_expiry_during_locked_execution_cannot_duplicate_student(self):
        job = self.make_job()
        from students import student_import_batch_service as service

        real_create = service._create_student_for_import_row
        creation_started = Event()
        allow_creation_to_finish = Event()

        def pause_during_creation(**kwargs):
            creation_started.set()
            if not allow_creation_to_finish.wait(timeout=5):
                raise RuntimeError("timed out waiting for concurrent claim")
            return real_create(**kwargs)

        with patch.object(
            service,
            "_create_student_for_import_row",
            side_effect=pause_during_creation,
        ):
            _, claims = _claim_rows(job_id=job.pk, batch_size=1)
            lease_expires_at = job.rows.get().lease_expires_at

            def execute_claim():
                connections.close_all()
                try:
                    return _execute_claimed_row(
                        claim=claims[0],
                        actor=self.actor,
                    )
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(execute_claim)
                try:
                    self.assertTrue(creation_started.wait(timeout=5))
                    with patch.object(
                        service.timezone,
                        "now",
                        return_value=lease_expires_at + timedelta(seconds=1),
                    ):
                        _, competing_claims = _claim_rows(
                            job_id=job.pk,
                            batch_size=1,
                        )
                    self.assertEqual(competing_claims, [])
                finally:
                    allow_creation_to_finish.set()
                result = future.result(timeout=10)

        self.assertEqual(result.status, StudentImportRow.Status.SUCCEEDED)
        self.assertEqual(Student.objects.count(), 1)
