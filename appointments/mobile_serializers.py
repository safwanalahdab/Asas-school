from datetime import datetime

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
            "requested_time",
            "request_reason",
            "status",
            "status_display",
            "approval_note",
            "rejection_reason",
            "created_at",
            "decided_at",
        )
        read_only_fields = (
            "id",
            "status",
            "status_display",
            "approval_note",
            "rejection_reason",
            "created_at",
            "decided_at",
        )

        extra_kwargs = {
            "requested_time": {
                "required": True,
                "allow_null": False,
            },
        }

    def validate(self, attrs):
        attrs = super().validate(attrs)
        requested_date = attrs.get("requested_date")
        requested_time = attrs.get("requested_time")

        if requested_date is None or requested_time is None:
            return attrs

        requested_at = datetime.combine(requested_date, requested_time)
        if timezone.is_naive(requested_at):
            requested_at = timezone.make_aware(
                requested_at,
                timezone.get_current_timezone(),
            )

        if requested_at <= timezone.now():
            raise serializers.ValidationError(
                {
                    "requested_time": (
                        "لا يمكن طلب موعد في وقت سابق للوقت الحالي."
                    )
                }
            )

        return attrs

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
