from django.db.models import Q
from django.db.models.functions import Concat
from django.db.models import Value

from django_filters import rest_framework as filters

from .models import AppointmentRequest


class AppointmentRequestFilter(
    filters.FilterSet,
):
    status = filters.ChoiceFilter(
        choices=AppointmentRequest.Status.choices,
    )

    requested_date = filters.DateFilter(
        field_name="requested_date",
    )

    guardian = filters.UUIDFilter(
        field_name="guardian_id",
    )

    search = filters.CharFilter(
        method="filter_search",
    )

    class Meta:
        model = AppointmentRequest

        fields = (
            "status",
            "requested_date",
            "guardian",
        )

    def filter_search(
        self,
        queryset,
        name,
        value,
    ):
        value = value.strip()

        if not value:
            return queryset

        queryset = queryset.annotate(
            guardian_full_name_search=Concat(
                "guardian__first_name",
                Value(" "),
                "guardian__last_name",
            ),
        )

        return queryset.filter(
            Q(
                guardian__username__icontains=value,
            )
            | Q(
                guardian__first_name__icontains=value,
            )
            | Q(
                guardian__last_name__icontains=value,
            )
            | Q(
                guardian_full_name_search__icontains=value,
            )
        ).distinct()