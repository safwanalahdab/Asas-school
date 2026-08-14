import uuid

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "CREATE", "إنشاء"
        UPDATE = "UPDATE", "تعديل"
        DELETE = "DELETE", "حذف"
        ACTIVATE = "ACTIVATE", "تفعيل"
        DEACTIVATE = "DEACTIVATE", "تعطيل"
        TRANSFER = "TRANSFER", "نقل"
        END = "END", "إنهاء"
        REOPEN = "REOPEN", "إعادة فتح"
        RESET_PASSWORD = "RESET_PASSWORD", "إعادة تعيين كلمة المرور"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="audit_logs"
    )
    action = models.CharField(max_length=30, choices=Action.choices)
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=255)
    resource_display = models.CharField(max_length=255)
    changes = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_logs_audit_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["actor"], name="audit_actor_idx"),
            models.Index(fields=["resource_type", "resource_id"], name="audit_resource_idx"),
            models.Index(fields=["created_at"], name="audit_created_idx"),
        ]

    def __str__(self):
        return f"{self.get_action_display()} - {self.resource_display}"
