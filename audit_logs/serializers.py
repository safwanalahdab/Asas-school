from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    module_display = serializers.CharField(source="get_module_display", read_only=True)
    action_display = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = AuditLog
        fields = (
            "id", "actor", "actor_display", "module", "module_display",
            "action", "action_display", "message", "target_type", "target_id",
            "target_display", "metadata", "ip_address", "created_at",
        )
        read_only_fields = fields
