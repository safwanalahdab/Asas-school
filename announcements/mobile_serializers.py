from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from .models import Announcement


class MobileAnnouncementSerializer(serializers.ModelSerializer):
    scope_display = serializers.CharField(source="get_scope_display", read_only=True)
    is_active = serializers.SerializerMethodField()

    class Meta:
        model = Announcement
        fields = (
            "id", "title", "content", "scope", "scope_display", "publish_date",
            "expiry_date", "is_active", "attachment", "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.BooleanField)
    def get_is_active(self, obj):
        return True


class MobileAnnouncementMetaSerializer(serializers.Serializer):
    requester_role = serializers.JSONField(allow_null=True)


class MobileAnnouncementsResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=True)
    code = serializers.CharField(default="MOBILE_CHILD_ANNOUNCEMENTS_RETRIEVED")
    message = serializers.CharField()
    data = MobileAnnouncementSerializer(many=True)
    meta = MobileAnnouncementMetaSerializer()


class MobileAnnouncementsErrorSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=False)
    code = serializers.CharField()
    message = serializers.CharField()
    meta = MobileAnnouncementMetaSerializer()
