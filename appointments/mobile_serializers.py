from django.utils import timezone
from rest_framework import serializers

from .models import AppointmentRequest


class MobileAppointmentRequestSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )
    rejection_reason = serializers.CharField(
        source="decision_reason",
        read_only=True,
    )

    class Meta:
        model = AppointmentRequest
        fields = (
            "id",
            "requested_date",
            "request_reason",
            "status",
            "status_display",
            "rejection_reason",
            "created_at",
            "decided_at",
        )
        read_only_fields = (
            "id",
            "status",
            "status_display",
            "rejection_reason",
            "created_at",
            "decided_at",
        )

    def validate_requested_date(self, value):
        if value < timezone.localdate():
            raise serializers.ValidationError(
                "لا يمكن طلب موعد بتاريخ سابق."
            )
        return value

    def validate_request_reason(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError(
                "يجب إدخال سبب طلب الحضور."
            )
        return value
