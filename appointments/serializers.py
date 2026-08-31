from django.utils import timezone

from rest_framework import serializers

from .models import AppointmentRequest


class AppointmentRequestSerializer(
    serializers.ModelSerializer,
):
    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    guardian_username = serializers.CharField(
        source="guardian.username",
        read_only=True,
    )

    guardian_display = serializers.SerializerMethodField()

    decided_by_username = serializers.CharField(
        source="decided_by.username",
        read_only=True,
    )

    decided_by_display = serializers.SerializerMethodField()

    class Meta:
        model = AppointmentRequest

        fields = (
            "id",

            "guardian",
            "guardian_username",
            "guardian_display",

            "requested_date",
            "request_reason",

            "status",
            "status_display",

            "decision_reason",

            "decided_by",
            "decided_by_username",
            "decided_by_display",

            "decided_at",

            "created_at",
            "updated_at",
        )

        read_only_fields = (
            "id",

            "guardian",

            "status",
            "status_display",

            "decision_reason",

            "decided_by",
            "decided_by_username",
            "decided_by_display",

            "decided_at",

            "created_at",
            "updated_at",
        )

    def get_guardian_display(
        self,
        obj,
    ):
        return (
            obj.guardian.get_full_name()
            or obj.guardian.username
        )

    def get_decided_by_display(
        self,
        obj,
    ):
        if not obj.decided_by:
            return None

        return (
            obj.decided_by.get_full_name()
            or obj.decided_by.username
        )

    def validate_requested_date(
        self,
        value,
    ):
        today = timezone.localdate()

        if value < today:
            raise serializers.ValidationError(
                "لا يمكن طلب موعد بتاريخ سابق."
            )

        return value

    def validate_request_reason(
        self,
        value,
    ):
        value = value.strip()

        if not value:
            raise serializers.ValidationError(
                "يجب إدخال سبب طلب الحضور."
            )

        return value


class AppointmentDecisionSerializer(
    serializers.Serializer,
):
    decision_reason = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )


class AppointmentApprovalSerializer(serializers.Serializer):
    pass
