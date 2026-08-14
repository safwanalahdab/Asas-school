from django.db import transaction

from .models import AuditLog
from .services import changed_fields, log_event, safe_snapshot


class AuditModelViewSetMixin:
    @transaction.atomic
    def perform_create(self, serializer):
        instance = serializer.save()
        log_event(
            actor=self.request.user, action=AuditLog.Action.CREATE,
            instance=instance, changes={"created_record": safe_snapshot(instance)},
        )

    @transaction.atomic
    def perform_update(self, serializer):
        changes = changed_fields(serializer.instance, serializer.validated_data)
        instance = serializer.save()
        log_event(
            actor=self.request.user, action=AuditLog.Action.UPDATE,
            instance=instance, changes=changes,
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        snapshot = safe_snapshot(instance)
        resource_display = str(instance)
        resource_id = str(instance.pk)
        resource_type = instance._meta.label
        instance.delete()
        AuditLog.objects.create(
            actor=self.request.user, action=AuditLog.Action.DELETE,
            resource_type=resource_type, resource_id=resource_id,
            resource_display=resource_display[:255],
            changes={"deleted_record": snapshot},
        )
