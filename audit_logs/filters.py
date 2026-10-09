from datetime import datetime, time, timedelta

from django.utils import timezone
from django_filters import rest_framework as filters

from .models import AuditLog


def _local_day_start(day):
    return timezone.make_aware(
        datetime.combine(day, time.min), timezone.get_current_timezone()
    )


class AuditLogFilter(filters.FilterSet):
    # Ranges on the raw column (instead of created_at__date) keep the
    # created_at index usable while matching the same local calendar days.
    date_from = filters.DateFilter(field_name="created_at", method="filter_date_from")
    date_to = filters.DateFilter(field_name="created_at", method="filter_date_to")

    class Meta:
        model = AuditLog
        fields = ("actor", "module", "action")

    def filter_date_from(self, queryset, name, value):
        return queryset.filter(created_at__gte=_local_day_start(value))

    def filter_date_to(self, queryset, name, value):
        return queryset.filter(
            created_at__lt=_local_day_start(value + timedelta(days=1))
        )
