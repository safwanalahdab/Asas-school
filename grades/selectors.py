from decimal import Decimal

from django.db.models import Prefetch

from rest_framework.exceptions import ValidationError

from students.models import Enrollment

from .models import (
    Assessment,
    StudentScore,
)


ZERO_SCORE = Decimal("0.00")


def get_assessment_score_rows(
    *,
    assessment,
):
    score_queryset = (
        StudentScore.objects
        .filter(
            assessment=assessment,
        )
        .select_related(
            "updated_by",
        )
    )

    enrollments = (
        Enrollment.objects
        .filter(
            academic_year=assessment.section.academic_year,
            section=assessment.section,
        )
        .select_related(
            "student",
        )
        .prefetch_related(
            Prefetch(
                "assessment_scores",
                queryset=score_queryset,
                to_attr="selected_assessment_scores",
            )
        )
        .order_by(
            "student__first_name",
            "student__last_name",
        )
    )

    rows = []

    for enrollment in enrollments:
        student_score = None

        if enrollment.selected_assessment_scores:
            student_score = (
                enrollment
                .selected_assessment_scores[0]
            )

        rows.append(
            {
                "enrollment": enrollment.id,
                "student": enrollment.student_id,
                "student_display": (
                    enrollment.student.full_name
                ),
                "score": (
                    student_score.score
                    if student_score is not None
                    else None
                ),
                "updated_by": (
                    student_score.updated_by_id
                    if student_score is not None
                    else None
                ),
                "updated_by_username": (
                    student_score.updated_by.username
                    if student_score is not None
                    else None
                ),
                "updated_at": (
                    student_score.updated_at
                    if student_score is not None
                    else None
                ),
            }
        )

    return rows


def get_student_term_results(
    *,
    enrollment,
    term,
    published_only=False,
):
    if (
        enrollment.academic_year_id
        != term.academic_year_id
    ):
        raise ValidationError(
            {
                "term": (
                    "الفصل الدراسي لا يتبع السنة "
                    "الدراسية الخاصة بتسجيل الطالب."
                )
            }
        )

    score_queryset = (
        StudentScore.objects
        .filter(
            enrollment=enrollment,
        )
    )

    assessments = (
        Assessment.objects
        .filter(
            section=enrollment.section,
            term=term,
        )
        .select_related(
            "grade_subject",
            "grade_subject__subject",
        )
        .prefetch_related(
            Prefetch(
                "scores",
                queryset=score_queryset,
                to_attr="selected_student_scores",
            )
        )
        .order_by(
            "grade_subject__subject__name",
            "assessment_date",
            "created_at",
        )
    )

    if published_only:
        assessments = assessments.filter(
            status=Assessment.Status.PUBLISHED,
        )

    grouped_results = {}

    for assessment in assessments:
        grade_subject = assessment.grade_subject

        group_key = grade_subject.id

        if group_key not in grouped_results:
            grouped_results[group_key] = {
                "grade_subject": grade_subject.id,
                "subject": grade_subject.subject_id,
                "subject_display": (
                    grade_subject.subject.name
                ),
                "assessments": [],
                "total_score": ZERO_SCORE,
                "total_max_score": ZERO_SCORE,
                "is_complete": True,
            }

        student_score = None

        if assessment.selected_student_scores:
            student_score = (
                assessment
                .selected_student_scores[0]
            )

        score_value = (
            student_score.score
            if student_score is not None
            else None
        )

        grouped_results[
            group_key
        ]["assessments"].append(
            {
                "assessment": assessment.id,
                "title": assessment.title,
                "score": score_value,
                "max_score": assessment.max_score,
                "assessment_date": (
                    assessment.assessment_date
                ),
                "status": assessment.status,
            }
        )

        if score_value is not None:
            grouped_results[
                group_key
            ]["total_score"] += score_value
        else:
            grouped_results[
                group_key
            ]["is_complete"] = False

        grouped_results[
            group_key
        ]["total_max_score"] += (
            assessment.max_score
        )

    return list(
        grouped_results.values()
    )