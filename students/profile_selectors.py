from decimal import Decimal
from uuid import UUID

from django.db.models import Count, OuterRef, Q, Subquery
from rest_framework.exceptions import NotFound, ValidationError

from academics.models import AcademicYear
from attendance.models import AttendanceRecord
from behavior.models import BehaviorNote
from finance.models import StudentFinancialAccount
from grades.models import AssessmentSection, StudentScore

from .models import Enrollment, GuardianStudent, Student, StudentHealthProfile


RECORDED_ATTENDANCE_STATUSES = (
    AttendanceRecord.Status.PRESENT,
    AttendanceRecord.Status.ABSENT,
)


def get_profile_student(student_id):
    student = Student.objects.filter(pk=student_id).first()
    if student is None:
        raise NotFound(
            {
                "code": "STUDENT_NOT_FOUND",
                "detail": "الطالب المطلوب غير موجود.",
            }
        )
    return student


def get_profile_academic_year(raw_academic_year):
    if raw_academic_year:
        try:
            academic_year_id = UUID(raw_academic_year)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValidationError(
                {
                    "code": "INVALID_ACADEMIC_YEAR",
                    "message": "السنة الدراسية المحددة غير صالحة.",
                    "academic_year": "يجب إرسال معرّف UUID صالح.",
                }
            ) from exc

        academic_year = AcademicYear.objects.filter(pk=academic_year_id).first()
        if academic_year is None:
            raise ValidationError(
                {
                    "code": "INVALID_ACADEMIC_YEAR",
                    "message": "السنة الدراسية المحددة غير موجودة.",
                    "academic_year": "لم يتم العثور على السنة الدراسية المحددة.",
                }
            )
        return academic_year

    return AcademicYear.objects.filter(status=AcademicYear.Status.ACTIVE).first()


def get_profile_guardians(student):
    return GuardianStudent.objects.filter(
        student=student,
        is_active=True,
    ).select_related("guardian")


def get_profile_health(student):
    return StudentHealthProfile.objects.filter(student=student).first()


def get_profile_enrollment(student, academic_year):
    if academic_year is None:
        return None
    return (
        Enrollment.objects.filter(student=student, academic_year=academic_year)
        .select_related("academic_year", "section", "section__grade_level")
        .first()
    )


def get_attendance_data(enrollment):
    if enrollment is None:
        return AttendanceRecord.objects.none(), empty_attendance_summary()

    records = (
        AttendanceRecord.objects.filter(
            enrollment=enrollment,
            status__in=RECORDED_ATTENDANCE_STATUSES,
        )
        .select_related("sheet", "sheet__section")
        .order_by("-sheet__attendance_date", "-created_at")
    )
    counts = records.aggregate(
        total_recorded_days=Count("id"),
        present_count=Count("id", filter=Q(status=AttendanceRecord.Status.PRESENT)),
        absent_count=Count("id", filter=Q(status=AttendanceRecord.Status.ABSENT)),
        excused_absence_count=Count(
            "id",
            filter=Q(
                status=AttendanceRecord.Status.ABSENT,
                absence_type=AttendanceRecord.AbsenceType.EXCUSED,
            ),
        ),
        unexcused_absence_count=Count(
            "id",
            filter=Q(
                status=AttendanceRecord.Status.ABSENT,
                absence_type=AttendanceRecord.AbsenceType.UNEXCUSED,
            ),
        ),
    )
    total = counts["total_recorded_days"]
    rate = (
        Decimal(counts["present_count"]) / Decimal(total) * Decimal("100")
        if total
        else Decimal("0")
    )
    counts["attendance_rate_percentage"] = format(rate.quantize(Decimal("0.01")), ".2f")
    return records, counts


def empty_attendance_summary():
    return {
        "total_recorded_days": 0,
        "present_count": 0,
        "absent_count": 0,
        "excused_absence_count": 0,
        "unexcused_absence_count": 0,
        "attendance_rate_percentage": "0.00",
    }


def get_grade_records(enrollment):
    if enrollment is None:
        return StudentScore.objects.none()

    publication = AssessmentSection.objects.filter(
        assessment_id=OuterRef("assessment_id"),
        section_id=OuterRef("recorded_section_id"),
    )
    return (
        StudentScore.objects.filter(enrollment=enrollment)
        .select_related(
            "assessment",
            "assessment__term",
            "assessment__grade_subject__subject",
            "recorded_section",
        )
        .annotate(
            publication_status=Subquery(publication.values("status")[:1]),
            publication_published_at=Subquery(publication.values("published_at")[:1]),
        )
        .order_by(
            "assessment__term__number",
            "assessment__grade_subject__subject__name",
            "assessment__assessment_date",
            "assessment__created_at",
            "id",
        )
    )


def get_behavior_data(enrollment):
    if enrollment is None:
        return BehaviorNote.objects.none(), empty_behavior_summary()

    notes = BehaviorNote.objects.filter(enrollment=enrollment).order_by(
        "-occurred_on", "-created_at"
    )
    summary = notes.aggregate(
        total_notes_count=Count("id"),
        positive_notes_count=Count(
            "id", filter=Q(note_type=BehaviorNote.Type.POSITIVE)
        ),
        negative_notes_count=Count(
            "id", filter=Q(note_type=BehaviorNote.Type.NEGATIVE)
        ),
    )
    return notes, summary


def empty_behavior_summary():
    return {
        "total_notes_count": 0,
        "positive_notes_count": 0,
        "negative_notes_count": 0,
    }


def get_financial_account(enrollment):
    if enrollment is None:
        return None
    return (
        StudentFinancialAccount.objects.filter(enrollment=enrollment)
        .select_related("tuition_plan")
        .first()
    )
