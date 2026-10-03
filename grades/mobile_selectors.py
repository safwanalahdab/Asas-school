from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

from academics.models import Term
from students.models import StudentAuditLog

from .models import AssessmentSection
from .selectors import get_enrollment_section_id_on_date, get_student_term_results

ZERO = Decimal("0.00")
PERCENT_QUANTUM = Decimal("0.01")


def get_mobile_published_term_results(*, enrollment, term):
    """Shape results for mobile after section-aware historical reconstruction."""
    reconstructed = get_student_term_results(
        enrollment=enrollment,
        term=term,
        published_only=False,
    )
    subjects = []
    for subject in reconstructed:
        assessments = [
            {
                "id": item["assessment"],
                "title": item["title"],
                "assessment_date": item["assessment_date"],
                "score": item["score"],
                "max_score": item["max_score"],
            }
            for item in subject["assessments"]
            if item["status"] == AssessmentSection.Status.PUBLISHED
        ]
        if not assessments:
            continue

        total_score = sum(
            (item["score"] for item in assessments if item["score"] is not None),
            ZERO,
        )
        total_max_score = sum(
            (item["max_score"] for item in assessments),
            ZERO,
        )
        is_complete = all(item["score"] is not None for item in assessments)
        percentage = None
        if is_complete and total_max_score > ZERO:
            percentage = (
                total_score / total_max_score * Decimal("100")
            ).quantize(PERCENT_QUANTUM, rounding=ROUND_HALF_UP)

        subjects.append({
            "grade_subject": subject["grade_subject"],
            "subject": {
                "id": subject["subject"],
                "name": subject["subject_display"],
            },
            "assessments": assessments,
            "total_score": total_score,
            "total_max_score": total_max_score,
            "percentage": percentage,
            "is_complete": is_complete,
        })
    return subjects


def get_mobile_grades_data(*, student, enrollment, term=None):
    if enrollment is None:
        return {
            "student": {"id": student.id, "full_name": student.full_name},
            "academic_year": None,
            "terms": [],
        }

    terms = Term.objects.filter(academic_year=enrollment.academic_year)
    if term is not None:
        terms = terms.filter(pk=term.pk)
    terms = terms.order_by("number")

    return {
        "student": {"id": student.id, "full_name": student.full_name},
        "academic_year": {
            "id": enrollment.academic_year_id,
            "name": enrollment.academic_year.name,
        },
        "terms": [
            {
                "id": current_term.id,
                "number": current_term.number,
                "number_display": current_term.get_number_display(),
                "start_date": current_term.start_date,
                "end_date": current_term.end_date,
                "subjects": get_mobile_published_term_results(
                    enrollment=enrollment,
                    term=current_term,
                ),
            }
            for current_term in terms
        ],
    }


def get_mobile_exams(*, enrollment, filters):
    """Return published exam schedules for the student's section on each date."""
    if enrollment is None:
        return []

    transfer_logs = list(
        StudentAuditLog.objects.filter(
            enrollment=enrollment,
            event_type=StudentAuditLog.EventType.SECTION_TRANSFER,
        ).order_by("created_at", "id")
    )
    historical_section_ids = {enrollment.section_id}
    for transfer in transfer_logs:
        historical_section_ids.add(transfer.old_section_id)
        historical_section_ids.add(transfer.new_section_id)

    today = timezone.localdate()
    view = filters["view"]
    queryset = AssessmentSection.objects.filter(
        schedule_status=AssessmentSection.ScheduleStatus.PUBLISHED,
        section_id__in=historical_section_ids,
        section__academic_year=enrollment.academic_year,
        section__grade_level=enrollment.section.grade_level,
        assessment__grade_subject__academic_year=enrollment.academic_year,
        assessment__grade_subject__grade_level=enrollment.section.grade_level,
        assessment__term__academic_year=enrollment.academic_year,
        assessment__assessment_date__gte=enrollment.enrollment_date,
    )

    if view == "upcoming":
        queryset = queryset.filter(assessment__assessment_date__gte=today)
    elif view == "past":
        queryset = queryset.filter(assessment__assessment_date__lt=today)
    if filters.get("date_from"):
        queryset = queryset.filter(
            assessment__assessment_date__gte=filters["date_from"]
        )
    if filters.get("date_to"):
        queryset = queryset.filter(
            assessment__assessment_date__lte=filters["date_to"]
        )
    if filters.get("term"):
        queryset = queryset.filter(assessment__term_id=filters["term"])
    if filters.get("subject"):
        queryset = queryset.filter(
            assessment__grade_subject__subject_id=filters["subject"]
        )

    candidates = queryset.select_related(
        "assessment",
        "assessment__grade_subject",
        "assessment__grade_subject__subject",
        "assessment__term",
        "section",
    )
    matching = [
        link
        for link in candidates
        if link.section_id
        == get_enrollment_section_id_on_date(
            enrollment=enrollment,
            target_date=link.assessment.assessment_date,
            transfer_logs=transfer_logs,
        )
    ]

    if view == "upcoming":
        matching.sort(
            key=lambda link: (
                link.assessment.assessment_date,
                link.assessment.title,
                str(link.assessment_id),
            )
        )
    elif view == "past":
        matching.sort(
            key=lambda link: (
                -link.assessment.assessment_date.toordinal(),
                link.assessment.title,
                str(link.assessment_id),
            )
        )
    else:
        matching.sort(
            key=lambda link: (
                0 if link.assessment.assessment_date >= today else 1,
                (
                    link.assessment.assessment_date.toordinal()
                    if link.assessment.assessment_date >= today
                    else -link.assessment.assessment_date.toordinal()
                ),
                link.assessment.title,
                str(link.assessment_id),
            )
        )

    return [
        {
            "id": link.assessment_id,
            "title": link.assessment.title,
            "subject": {
                "id": link.assessment.grade_subject.subject_id,
                "name": link.assessment.grade_subject.subject.name,
            },
            "assessment_date": link.assessment.assessment_date,
            "temporal_status": (
                "upcoming"
                if link.assessment.assessment_date >= today
                else "past"
            ),
            "term": {
                "id": link.assessment.term_id,
                "number": link.assessment.term.number,
                "number_display": link.assessment.term.get_number_display(),
            },
            "section": {
                "id": link.section_id,
                "name": link.section.name,
            },
            "max_score": link.assessment.max_score,
        }
        for link in matching
    ]
