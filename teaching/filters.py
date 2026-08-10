from django_filters import rest_framework as filters

from .models import TeacherAssignment


class TeacherAssignmentFilter(filters.FilterSet):
    academic_year = filters.UUIDFilter(
        field_name="grade_subject__academic_year",
    )

    grade_level = filters.UUIDFilter(
        field_name="grade_subject__grade_level",
    )

    subject = filters.UUIDFilter(
        field_name="grade_subject__subject",
    )

    class Meta:
        model = TeacherAssignment

        fields = (
            "teacher",
            "academic_year",
            "grade_level",
            "section",
            "subject",
        )