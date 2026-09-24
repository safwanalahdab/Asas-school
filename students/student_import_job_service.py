from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
from pathlib import Path, PurePosixPath

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction

from .models import StudentImportJob, StudentImportRow
from .student_import_excel import (
    MAX_FILE_SIZE_BYTES,
    ImportValidationError,
    read_student_import_xlsx,
)
from .student_import_reference_validation import (
    STATUS_INVALID,
    STATUS_READY,
    STATUS_REVIEW_REQUIRED,
    validate_student_import_references,
)


@dataclass(frozen=True)
class StudentImportJobCreationResult:
    job: StudentImportJob | None
    file_errors: list[ImportValidationError]

    @property
    def created(self):
        return self.job is not None

    def to_dict(self):
        if self.job is None:
            return {
                "created": False,
                "job": None,
                "file_errors": [error.to_dict() for error in self.file_errors],
            }
        return {
            "created": True,
            "job": {
                "id": str(self.job.id),
                "status": self.job.status,
                "total_rows": self.job.total_rows,
                "valid_rows": self.job.valid_rows,
                "invalid_rows": self.job.invalid_rows,
                "review_rows": self.job.review_rows,
            },
            "file_errors": [],
        }


def _file_error(code, detail):
    return ImportValidationError(code=code, detail=detail)


def _read_source(uploaded_file):
    if isinstance(uploaded_file, (str, Path)):
        with Path(uploaded_file).open("rb") as source:
            return source.read(MAX_FILE_SIZE_BYTES + 1)

    original_position = (
        uploaded_file.tell() if hasattr(uploaded_file, "tell") else None
    )
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    try:
        return uploaded_file.read(MAX_FILE_SIZE_BYTES + 1)
    finally:
        if original_position is not None and hasattr(uploaded_file, "seek"):
            uploaded_file.seek(original_position)


def _source_filename(uploaded_file, filename):
    if filename is not None:
        return str(filename)
    source_name = getattr(uploaded_file, "name", None)
    if source_name is not None:
        return str(source_name)
    if isinstance(uploaded_file, (str, Path)):
        return str(uploaded_file)
    return ""


def _safe_filename(filename):
    basename = PurePosixPath(str(filename).replace("\\", "/")).name
    safe_name = "".join(character for character in basename if character.isprintable())
    safe_name = safe_name.strip().strip(".")
    return (safe_name or "students.xlsx")[:255]


def _json_safe(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def _persist_validation_result(
    *,
    validation_result,
    created_by,
    original_filename,
    file_sha256,
    file_size,
):
    row_counts = {
        STATUS_READY: 0,
        STATUS_INVALID: 0,
        STATUS_REVIEW_REQUIRED: 0,
    }
    import_rows = []
    for result_row in validation_result.rows:
        row_counts[result_row.status] += 1
        normalized_data = dict(result_row.normalized_data)
        normalized_data["resolved_references"] = (
            result_row.resolved_references.to_dict()
        )
        import_rows.append(
            StudentImportRow(
                row_number=result_row.excel_row_number,
                normalized_data=_json_safe(normalized_data),
                status=result_row.status,
                validation_errors=_json_safe(
                    [error.to_dict() for error in result_row.validation_errors]
                ),
            )
        )

    total_rows = len(import_rows)
    job_status = (
        StudentImportJob.Status.READY
        if total_rows > 0
        and row_counts[STATUS_READY] == total_rows
        else StudentImportJob.Status.VALIDATION_FAILED
    )

    with transaction.atomic():
        job = StudentImportJob.objects.create(
            created_by=created_by,
            original_filename=original_filename,
            file_sha256=file_sha256,
            file_size=file_size,
            status=job_status,
            total_rows=total_rows,
            valid_rows=row_counts[STATUS_READY],
            invalid_rows=row_counts[STATUS_INVALID],
            review_rows=row_counts[STATUS_REVIEW_REQUIRED],
        )
        for import_row in import_rows:
            import_row.job = job
        StudentImportRow.objects.bulk_create(import_rows)
    return job


def create_student_import_job(*, uploaded_file, created_by, filename=None):
    source_filename = _source_filename(uploaded_file, filename)
    try:
        content = _read_source(uploaded_file)
    except (OSError, AttributeError, TypeError, ValueError):
        error = _file_error("file_read_error", "تعذرت قراءة الملف المرفوع.")
        return StudentImportJobCreationResult(job=None, file_errors=[error])

    if not isinstance(content, (bytes, bytearray)):
        error = _file_error("file_read_error", "تعذرت قراءة الملف المرفوع.")
        return StudentImportJobCreationResult(job=None, file_errors=[error])

    content = bytes(content)
    read_result = read_student_import_xlsx(
        BytesIO(content),
        filename=source_filename,
    )
    if read_result.file_errors:
        return StudentImportJobCreationResult(
            job=None,
            file_errors=list(read_result.file_errors),
        )

    validation_result = validate_student_import_references(read_result)
    job = _persist_validation_result(
        validation_result=validation_result,
        created_by=created_by,
        original_filename=_safe_filename(source_filename),
        file_sha256=hashlib.sha256(content).hexdigest(),
        file_size=len(content),
    )
    return StudentImportJobCreationResult(job=job, file_errors=[])
