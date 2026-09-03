from rest_framework import serializers

from .models import Notification, PushDevice


class MobileNotificationSerializer(serializers.ModelSerializer):
    type = serializers.CharField(source="notification_type", read_only=True)
    type_display = serializers.CharField(
        source="get_notification_type_display",
        read_only=True,
    )
    student = serializers.SerializerMethodField()
    data = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = (
            "id",
            "type",
            "type_display",
            "title",
            "body",
            "is_read",
            "read_at",
            "created_at",
            "student",
            "resource_type",
            "resource_id",
            "data",
        )
        read_only_fields = fields

    def get_student(self, obj) -> dict | None:
        if obj.student is None:
            return None
        return {
            "id": str(obj.student_id),
            "full_name": obj.student.full_name,
        }

    def get_data(self, obj) -> dict:
        return {
            "student_id": str(obj.student_id) if obj.student_id else None,
            "resource_type": obj.resource_type,
            "resource_id": str(obj.resource_id) if obj.resource_id else None,
        }


class MobilePushDeviceRegistrationSerializer(serializers.Serializer):
    installation_id = serializers.UUIDField(required=True)
    fcm_token = serializers.CharField(required=True, trim_whitespace=True)
    platform = serializers.ChoiceField(choices=PushDevice.Platform.choices)
    device_name = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        max_length=150,
        default="",
    )

    def validate_fcm_token(self, value):
        if not value:
            raise serializers.ValidationError("FCM token is required.")
        return value


class MobilePushDeviceUnregisterSerializer(serializers.Serializer):
    installation_id = serializers.UUIDField(required=True)


class MobilePushDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PushDevice
        fields = (
            "id",
            "installation_id",
            "platform",
            "device_name",
            "is_active",
            "last_seen_at",
            "created_at",
        )
        read_only_fields = fields
