from django.db.models import Q
from django.utils import timezone
from django_filters import rest_framework as filters

from .models import Announcement


class AnnouncementFilter(filters.FilterSet):
    scope = filters.ChoiceFilter(
        choices=Announcement.Scope.choices,
    )

    grade_level = filters.UUIDFilter(
        method="filter_grade_level",
    )

    section = filters.UUIDFilter(
        method="filter_section",
    )

    publish_from = filters.DateFilter(
        field_name="publish_date",
        lookup_expr="gte",
    )

    publish_to = filters.DateFilter(
        field_name="publish_date",
        lookup_expr="lte",
    )

    is_active = filters.BooleanFilter(
        method="filter_is_active",
    )

    class Meta:
        model = Announcement

        fields = (
            "scope",
        )

    def filter_grade_level(self, queryset, name, value):
        return queryset.filter(
            grade_levels__id=value,
        ).distinct()

    def filter_section(self, queryset, name, value):
        return queryset.filter(
            sections__id=value,
        ).distinct()

    def filter_is_active(self, queryset, name, value):
        today = timezone.localdate()

        if value:
            return queryset.filter(
                publish_date__lte=today,
            ).filter(
                Q(expiry_date__isnull=True)
                | Q(expiry_date__gte=today)
            )

        return queryset.filter(
            Q(publish_date__gt=today)
            | Q(expiry_date__lt=today)
        )