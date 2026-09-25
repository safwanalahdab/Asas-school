from dataclasses import dataclass
from datetime import timedelta
import uuid

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import StudentImportJob, StudentImportRow
from .student_import_row_execution import (
    StudentImportRowExecutionError,
    _create_student_for_import_row,
)


DEFAULT_BATCH_SIZE = 10
MAX_BATCH_SIZE = 100
LEASE_DURATION = timedelta(minutes=10)


class StudentImportBatchError(Exception):
    def __init__(self, *, code, detail):
        super().__init__(detail)
        self.code = code
        self.detail = detail

    def to_dict(self):
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class ClaimedImportRow:
    row_id: object
    lease_token: uuid.UUID


@dataclass(frozen=True)
class StudentImportBatchRowResult:
    row_id: object
    row_number: int
    status: str
    error: dict | None = None

    def to_dict(self):
        return {
            "row_id": str(self.row_id),
            "row_number": self.row_number,
            "status": self.status,
            "error": self.error,
        }


@dataclass(frozen=True)
class StudentImportBatchResult:
    job: StudentImportJob
    claimed_rows: int
    rows: list[StudentImportBatchRowResult]

    def to_dict(self):
        return {
            "job_id": str(self.job.id),
            "job_status": self.job.status,
            "claimed_rows": self.claimed_rows,
            "succeeded_rows": sum(
                row.status == StudentImportRow.Status.SUCCEEDED for row in self.rows
            ),
            "failed_rows": sum(
                row.status == StudentImportRow.Status.FAILED for row in self.rows
            ),
            "rows": [row.to_dict() for row in self.rows],
        }


def _validated_batch_size(batch_size):
    if isinstance(batch_size, bool) or not isinstance(batch_size, int):
        raise StudentImportBatchError(
            code="invalid_batch_size",
            detail="يجب أن يكون حجم الدفعة عددًا صحيحًا بين 1 و100.",
        )
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise StudentImportBatchError(
            code="invalid_batch_size",
            detail="يجب أن يكون حجم الدفعة عددًا صحيحًا بين 1 و100.",
        )
    return batch_size


def _raise_job_not_processable(job):
    raise StudentImportBatchError(
        code="job_not_processable",
        detail=(
            "لا يمكن بدء معالجة جلسة الاستيراد قبل اكتمال التحقق بنجاح، "
            "ولا يمكن إعادة فتح جلسة مكتملة."
        ),
    )


def _claim_rows(*, job_id, batch_size):
    claimed_at = timezone.now()
    lease_expires_at = claimed_at + LEASE_DURATION

    with transaction.atomic():
        job = StudentImportJob.objects.select_for_update().get(pk=job_id)
        if job.status in (
            StudentImportJob.Status.COMPLETED,
            StudentImportJob.Status.COMPLETED_WITH_ERRORS,
        ):
            return job, []

        if job.status == StudentImportJob.Status.READY:
            rows = job.rows.all()
            if (
                job.total_rows < 1
                or rows.count() != job.total_rows
                or rows.exclude(status=StudentImportRow.Status.READY).exists()
            ):
                _raise_job_not_processable(job)
            job.status = StudentImportJob.Status.PROCESSING
            job.started_at = job.started_at or claimed_at
            job.finished_at = None
        elif job.status == StudentImportJob.Status.PROCESSING:
            allowed_statuses = (
                StudentImportRow.Status.READY,
                StudentImportRow.Status.PROCESSING,
                StudentImportRow.Status.SUCCEEDED,
                StudentImportRow.Status.FAILED,
            )
            if (
                job.rows.count() != job.total_rows
                or job.rows.exclude(status__in=allowed_statuses).exists()
            ):
                _raise_job_not_processable(job)
        else:
            _raise_job_not_processable(job)

        job.batch_size = batch_size
        job.save(
            update_fields=[
                "status",
                "batch_size",
                "started_at",
                "finished_at",
                "updated_at",
            ]
        )

        eligible = Q(status=StudentImportRow.Status.READY) | Q(
            status=StudentImportRow.Status.PROCESSING,
            lease_expires_at__lte=claimed_at,
        )
        rows = list(
            StudentImportRow.objects.select_for_update(skip_locked=True)
            .filter(eligible, job=job)
            .order_by("row_number")[:batch_size]
        )

        claims = []
        for row in rows:
            token = uuid.uuid4()
            row.status = StudentImportRow.Status.PROCESSING
            row.lease_token = token
            row.lease_expires_at = lease_expires_at
            row.last_attempt_at = claimed_at
            row.attempt_count += 1
            claims.append(ClaimedImportRow(row_id=row.pk, lease_token=token))

        if rows:
            StudentImportRow.objects.bulk_update(
                rows,
                [
                    "status",
                    "lease_token",
                    "lease_expires_at",
                    "last_attempt_at",
                    "attempt_count",
                    "updated_at",
                ],
            )
        return job, claims


def _safe_row_error(error):
    return {
        "code": error.code,
        "detail": error.detail,
        "validation_errors": [
            item.to_dict() if hasattr(item, "to_dict") else item
            for item in error.validation_errors
        ],
    }


def _execute_claimed_row(*, claim, actor):
    with transaction.atomic():
        row = (
            StudentImportRow.objects.select_for_update(of=("self",))
            .select_related("job")
            .get(pk=claim.row_id)
        )
        now = timezone.now()
        if (
            row.status != StudentImportRow.Status.PROCESSING
            or row.lease_token != claim.lease_token
            or row.lease_expires_at is None
            or row.lease_expires_at <= now
        ):
            return StudentImportBatchRowResult(
                row_id=row.pk,
                row_number=row.row_number,
                status="lease_lost",
            )

        try:
            # This savepoint rolls back every created record for an expected row
            # failure while keeping the outer transaction available to persist it.
            with transaction.atomic():
                result = _create_student_for_import_row(
                    persisted_row=row,
                    actor=actor,
                )
        except StudentImportRowExecutionError as error:
            safe_error = _safe_row_error(error)
            row.status = StudentImportRow.Status.FAILED
            row.validation_errors = [safe_error]
            row.processed_at = timezone.now()
            row.lease_token = None
            row.lease_expires_at = None
            row.save(
                update_fields=[
                    "status",
                    "validation_errors",
                    "processed_at",
                    "lease_token",
                    "lease_expires_at",
                    "updated_at",
                ]
            )
            return StudentImportBatchRowResult(
                row_id=row.pk,
                row_number=row.row_number,
                status=row.status,
                error=safe_error,
            )

        row.student = result.student
        row.guardian = result.guardian
        row.enrollment = result.enrollment
        row.status = StudentImportRow.Status.SUCCEEDED
        row.validation_errors = []
        row.processed_at = timezone.now()
        row.lease_token = None
        row.lease_expires_at = None
        row.save(
            update_fields=[
                "student",
                "guardian",
                "enrollment",
                "status",
                "validation_errors",
                "processed_at",
                "lease_token",
                "lease_expires_at",
                "updated_at",
            ]
        )
        return StudentImportBatchRowResult(
            row_id=row.pk,
            row_number=row.row_number,
            status=row.status,
        )


def _refresh_job(job_id):
    with transaction.atomic():
        job = StudentImportJob.objects.select_for_update().get(pk=job_id)
        counts = {
            item["status"]: item["count"]
            for item in job.rows.values("status").annotate(count=Count("id"))
        }
        succeeded = counts.get(StudentImportRow.Status.SUCCEEDED, 0)
        failed = counts.get(StudentImportRow.Status.FAILED, 0)
        job.succeeded_rows = succeeded
        job.failed_rows = failed
        job.processed_rows = succeeded + failed

        still_processable = (
            counts.get(StudentImportRow.Status.READY, 0)
            + counts.get(StudentImportRow.Status.PROCESSING, 0)
        )
        if job.status == StudentImportJob.Status.PROCESSING and not still_processable:
            job.status = (
                StudentImportJob.Status.COMPLETED_WITH_ERRORS
                if failed
                else StudentImportJob.Status.COMPLETED
            )
            job.finished_at = timezone.now()

        job.save(
            update_fields=[
                "processed_rows",
                "succeeded_rows",
                "failed_rows",
                "status",
                "finished_at",
                "updated_at",
            ]
        )
        return job


def process_next_batch(*, job, actor, batch_size=DEFAULT_BATCH_SIZE):
    batch_size = _validated_batch_size(batch_size)
    persisted_job, claims = _claim_rows(
        job_id=job.pk,
        batch_size=batch_size,
    )

    row_results = []
    for claim in claims:
        row_result = _execute_claimed_row(claim=claim, actor=actor)
        row_results.append(row_result)
        _refresh_job(persisted_job.pk)

    persisted_job = _refresh_job(persisted_job.pk)
    return StudentImportBatchResult(
        job=persisted_job,
        claimed_rows=len(claims),
        rows=row_results,
    )
