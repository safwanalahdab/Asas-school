from decimal import Decimal

from django.db.models import Prefetch, Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from students.models import Enrollment, StudentAuditLog

from .models import Assessment, AssessmentSection, StudentScore

ZERO = Decimal("0.00")


def get_enrollment_section_id_on_date(*, enrollment, target_date, transfer_logs=None):
    """Reconstruct the enrollment's section at the start of a calendar date."""
    if transfer_logs is None:
        transfer_logs = StudentAuditLog.objects.filter(
            enrollment=enrollment,
            event_type=StudentAuditLog.EventType.SECTION_TRANSFER,
        ).order_by("created_at", "id")
    transfer_logs = list(transfer_logs)
    section_id = (
        transfer_logs[0].old_section_id
        if transfer_logs
        else enrollment.section_id
    )
    for transfer in transfer_logs:
        transfer_date = timezone.localtime(transfer.created_at).date()
        if transfer_date > target_date:
            break
        section_id = transfer.new_section_id
    return section_id


def get_assessment_score_rows(*, assessment, section):
    scores = StudentScore.objects.filter(assessment=assessment, recorded_section=section).select_related("updated_by")
    scored_ids = scores.values_list("enrollment_id", flat=True)
    transfer_history = StudentAuditLog.objects.filter(
        event_type=StudentAuditLog.EventType.SECTION_TRANSFER,
    ).order_by("created_at", "id")
    enrollments = Enrollment.objects.filter(
        Q(academic_year=section.academic_year, enrollment_date__lte=assessment.assessment_date)
        | Q(id__in=scored_ids)
    ).select_related("student").prefetch_related(
        Prefetch("assessment_scores", queryset=scores, to_attr="selected_scores"),
        Prefetch("audit_logs", queryset=transfer_history, to_attr="section_transfer_history"),
    ).distinct().order_by("student__first_name", "student__last_name")
    rows = []
    for enrollment in enrollments:
        item = enrollment.selected_scores[0] if enrollment.selected_scores else None
        if item is None and get_enrollment_section_id_on_date(
            enrollment=enrollment,
            target_date=assessment.assessment_date,
            transfer_logs=enrollment.section_transfer_history,
        ) != section.id:
            continue
        rows.append({
            "enrollment": enrollment.id, "student": enrollment.student_id,
            "student_display": enrollment.student.full_name,
            "score": item.score if item else None,
            "updated_by": item.updated_by_id if item else None,
            "updated_by_username": item.updated_by.username if item else None,
            "updated_at": item.updated_at if item else None,
        })
    return rows


def get_student_term_results(*, enrollment, term, published_only=False):
    if enrollment.academic_year_id != term.academic_year_id:
        raise ValidationError({"term": "الفصل الدراسي لا يتبع سنة تسجيل الطالب."})
    own_scores = StudentScore.objects.filter(enrollment=enrollment)
    transfer_logs = list(StudentAuditLog.objects.filter(
        enrollment=enrollment,
        event_type=StudentAuditLog.EventType.SECTION_TRANSFER,
    ).order_by("created_at", "id"))
    assessments = Assessment.objects.filter(term=term).filter(
        Q(assessment_date__gte=enrollment.enrollment_date)
        | Q(scores__enrollment=enrollment)
    )
    if published_only:
        assessments = assessments.filter(assessment_sections__status=AssessmentSection.Status.PUBLISHED)
    assessments = assessments.select_related("grade_subject__subject").prefetch_related(
        Prefetch("scores", queryset=own_scores, to_attr="selected_student_scores"),
        "assessment_sections",
    ).distinct().order_by("grade_subject__subject__name", "assessment_date", "created_at")
    grouped = {}
    for assessment in assessments:
        subject = assessment.grade_subject
        group = grouped.setdefault(subject.id, {
            "grade_subject": subject.id, "subject": subject.subject_id,
            "subject_display": subject.subject.name, "assessments": [],
            "total_score": ZERO, "total_max_score": ZERO, "is_complete": True,
        })
        item = assessment.selected_student_scores[0] if assessment.selected_student_scores else None
        historical_section_id = get_enrollment_section_id_on_date(
            enrollment=enrollment,
            target_date=assessment.assessment_date,
            transfer_logs=transfer_logs,
        )
        if item is None and not any(
            link.section_id == historical_section_id
            for link in assessment.assessment_sections.all()
        ):
            continue
        value = item.score if item else None
        link = next((x for x in assessment.assessment_sections.all() if item and x.section_id == item.recorded_section_id), None)
        if link is None:
            link = next((x for x in assessment.assessment_sections.all() if x.section_id == historical_section_id), None)
        group["assessments"].append({
            "assessment": assessment.id, "title": assessment.title, "score": value,
            "max_score": assessment.max_score, "assessment_date": assessment.assessment_date,
            "status": link.status if link else AssessmentSection.Status.DRAFT,
        })
        if value is None:
            group["is_complete"] = False
        else:
            group["total_score"] += value
        group["total_max_score"] += assessment.max_score
    return list(grouped.values())
