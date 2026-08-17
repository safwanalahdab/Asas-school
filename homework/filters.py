from django_filters import rest_framework as filters

from .models import Homework


class HomeworkFilter(filters.FilterSet):
    homework_from = filters.DateFilter(
        field_name="homework_date",
        lookup_expr="gte",
    )

    homework_to = filters.DateFilter(
        field_name="homework_date",
        lookup_expr="lte",
    )

    due_from = filters.DateFilter(
        field_name="due_date",
        lookup_expr="gte",
    )

    due_to = filters.DateFilter(
        field_name="due_date",
        lookup_expr="lte",
    )

    class Meta:
        model = Homework

        fields = (
            "teacher_assignment",
            "teacher_assignment__teacher",
            "teacher_assignment__section",
            "teacher_assignment__grade_subject",
            "teacher_assignment__grade_subject__subject",
            "teacher_assignment__grade_subject__academic_year",
        )