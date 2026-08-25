from django_filters import rest_framework as filters

from .models import Assessment, AssessmentSection


class AssessmentFilter(filters.FilterSet):
    academic_year = filters.UUIDFilter(
        field_name="grade_subject__academic_year_id",
    )

    term = filters.UUIDFilter(
        field_name="term_id",
    )

    grade_level = filters.UUIDFilter(
        field_name="grade_subject__grade_level_id",
    )

    section = filters.UUIDFilter(
        field_name="assessment_sections__section_id",
    )

    grade_subject = filters.UUIDFilter(
        field_name="grade_subject_id",
    )

    subject = filters.UUIDFilter(
        field_name="grade_subject__subject_id",
    )

    status = filters.ChoiceFilter(
        field_name="assessment_sections__status",
        choices=AssessmentSection.Status.choices,
    )

    assessment_from = filters.DateFilter(
        field_name="assessment_date",
        lookup_expr="gte",
    )

    assessment_to = filters.DateFilter(
        field_name="assessment_date",
        lookup_expr="lte",
    )

    class Meta:
        model = Assessment

        fields = ()
