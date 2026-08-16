from django_filters import rest_framework as filters

from .models import BehaviorNote


class BehaviorNoteFilter(filters.FilterSet):
    occurred_from = filters.DateFilter(
        field_name="occurred_on",
        lookup_expr="gte",
    )

    occurred_to = filters.DateFilter(
        field_name="occurred_on",
        lookup_expr="lte",
    )

    class Meta:
        model = BehaviorNote
        fields = (
            "note_type",
            "enrollment",
            "created_by",
        )