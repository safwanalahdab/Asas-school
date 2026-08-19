from django_filters import rest_framework as filters

from .models import SchoolRequest


class SchoolRequestFilter(filters.FilterSet):
    request_type = filters.ChoiceFilter(
        choices=SchoolRequest.RequestType.choices,
    )

    status = filters.ChoiceFilter(
        choices=SchoolRequest.Status.choices,
    )

    student = filters.UUIDFilter(
        field_name="student_id",
    )

    created_from = filters.DateFilter(
        field_name="created_at",
        lookup_expr="date__gte",
    )

    created_to = filters.DateFilter(
        field_name="created_at",
        lookup_expr="date__lte",
    )

    class Meta:
        model = SchoolRequest

        fields = (
            "request_type",
            "status",
            "student",
        )