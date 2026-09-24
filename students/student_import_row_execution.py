from dataclasses import dataclass

from django.db import transaction
from rest_framework.exceptions import ValidationError

from academics.models import AcademicYear, Section
from finance.services import ensure_financial_account_for_enrollment

from .models import StudentImportJob, StudentImportRow
from .serializers import EnrollmentSerializer
from .services import register_student
from .student_import_excel import StudentImportReadResult, StudentImportRowResult
from .student_import_reference_validation import (
    STATUS_READY,
    validate_student_import_references,
)


class StudentImportRowExecutionError(Exception):
    def __init__(self, *, code, detail, validation_errors=None):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.validation_errors = validation_errors or []

    def to_dict(self):
        return {
            "code": self.code,
            "detail": self.detail,
            "validation_errors": [
                error.to_dict() if hasattr(error, "to_dict") else error
                for error in self.validation_errors
            ],
        }


@dataclass(frozen=True)
class StudentImportRowExecutionResult:
    student: object
    health_profile: object
    guardian: object | None
    guardian_created: bool
    enrollment: object
    financial_account: object | None

    def to_dict(self):
        return {
            "student_id": str(self.student.id),
            "health_profile_id": str(self.health_profile.id),
            "guardian_id": str(self.guardian.id) if self.guardian else None,
            "guardian_created": self.guardian_created,
            "enrollment_id": str(self.enrollment.id),
            "financial_account_id": (
                str(self.financial_account.id) if self.financial_account else None
            ),
        }


def _raise_not_ready(code, detail):
    raise StudentImportRowExecutionError(code=code, detail=detail)


def _revalidate(import_row):
    normalized_data = dict(import_row.normalized_data)
    normalized_data.pop("resolved_references", None)
    read_result = StudentImportReadResult(
        data_row_count=1,
        rows=[
            StudentImportRowResult(
                excel_row_number=import_row.row_number,
                normalized_data=normalized_data,
                validation_errors=[],
            )
        ],
        file_errors=[],
    )
    validation_result = validate_student_import_references(read_result)
    result_row = validation_result.rows[0]
    if result_row.status != STATUS_READY:
        raise StudentImportRowExecutionError(
            code="row_revalidation_failed",
            detail="تغيّرت بيانات المدرسة أو ظهر اشتباه جديد، ولا يمكن تنفيذ هذا الصف.",
            validation_errors=result_row.validation_errors,
        )
    return result_row


@transaction.atomic
def execute_student_import_row(*, import_row, actor):
    persisted_row = StudentImportRow.objects.select_related("job").get(
        pk=import_row.pk
    )
    if persisted_row.status != StudentImportRow.Status.READY:
        _raise_not_ready(
            "row_not_ready",
            "لا يمكن تنفيذ صف استيراد غير جاهز.",
        )
    if persisted_row.job.status != StudentImportJob.Status.READY:
        _raise_not_ready(
            "job_not_ready",
            "لا يمكن تنفيذ صف من جلسة استيراد غير جاهزة.",
        )

    validated_row = _revalidate(persisted_row)
    references = validated_row.resolved_references
    if not (
        references.academic_year_id
        and references.grade_level_id
        and references.section_id
    ):
        _raise_not_ready(
            "missing_resolved_references",
            "تعذر حل المراجع الأكاديمية اللازمة لتنفيذ الصف.",
        )

    academic_year = AcademicYear.objects.select_for_update().get(
        pk=references.academic_year_id
    )
    section = (
        Section.objects.select_for_update()
        .select_related("grade_level")
        .get(pk=references.section_id)
    )
    if (
        section.academic_year_id != academic_year.id
        or str(section.grade_level_id) != references.grade_level_id
        or academic_year.status == AcademicYear.Status.CLOSED
    ):
        _raise_not_ready(
            "academic_references_changed",
            "تغيّرت المراجع الأكاديمية ولا يمكن تنفيذ الصف.",
        )

    normalized_data = validated_row.normalized_data
    try:
        registration_result = register_student(
            student_data=dict(normalized_data["student"]),
            health_profile_data=dict(normalized_data.get("health_profile") or {}),
            guardian_data=(
                dict(normalized_data["guardian"])
                if normalized_data.get("guardian")
                else None
            ),
        )
        student = registration_result["student"]
        guardian_account = registration_result["guardian_account"]
        guardian_created = guardian_account["status"] == "created"
        guardian_account["temporary_password"] = None

        guardian = None
        if normalized_data.get("guardian"):
            guardian = student.guardian_link.guardian

        enrollment_serializer = EnrollmentSerializer(
            data={
                "student": str(student.id),
                "academic_year": str(academic_year.id),
                "section": str(section.id),
                "enrollment_date": normalized_data["enrollment"][
                    "enrollment_date"
                ],
                "usual_arrival_method": normalized_data["enrollment"][
                    "usual_arrival_method"
                ],
                "usual_departure_method": normalized_data["enrollment"][
                    "usual_departure_method"
                ],
            }
        )
        enrollment_serializer.is_valid(raise_exception=True)
        enrollment = enrollment_serializer.save()
        financial_account = ensure_financial_account_for_enrollment(
            enrollment=enrollment,
            actor=actor,
        )
    except ValidationError as exc:
        raise StudentImportRowExecutionError(
            code="row_creation_failed",
            detail="تعذر إنشاء الطالب وجميع السجلات المرتبطة به.",
        ) from exc

    return StudentImportRowExecutionResult(
        student=student,
        health_profile=student.health_profile,
        guardian=guardian,
        guardian_created=guardian_created,
        enrollment=enrollment,
        financial_account=financial_account,
    )
