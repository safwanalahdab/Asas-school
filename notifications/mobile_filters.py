from rest_framework.exceptions import ValidationError
from rest_framework.filters import BaseFilterBackend


class MobileNotificationFilter(BaseFilterBackend):
    allowed_values = {"true": True, "false": False}

    def filter_queryset(self, request, queryset, view):
        if "is_read" not in request.query_params:
            return queryset

        raw_value = request.query_params.get("is_read")
        if raw_value not in self.allowed_values:
            raise ValidationError(
                {"is_read": ["يجب أن تكون القيمة true أو false فقط."]}
            )
        return queryset.filter(is_read=self.allowed_values[raw_value])
