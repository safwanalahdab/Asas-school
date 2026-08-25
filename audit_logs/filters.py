from django_filters import rest_framework as filters

from .models import AuditLog


class AuditLogFilter(filters.FilterSet):
    date_from = filters.DateFilter(field_name="created_at", lookup_expr="date__gte")
    date_to = filters.DateFilter(field_name="created_at", lookup_expr="date__lte")

    class Meta:
        model = AuditLog
        fields = ("actor", "module", "action")
