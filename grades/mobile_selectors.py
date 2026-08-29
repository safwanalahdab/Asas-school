from decimal import Decimal, ROUND_HALF_UP

from academics.models import Term

from .models import AssessmentSection
from .selectors import get_student_term_results

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
