import uuid

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    class Module(models.TextChoices):
        ACCOUNTS = "accounts", "الحسابات"
        STUDENTS = "students", "الطلاب"
        ACADEMICS = "academics", "الشؤون الأكاديمية"
        ATTENDANCE = "attendance", "الحضور"
        GRADES = "grades", "العلامات"
        FINANCE = "finance", "المالية"
        OTHER = "other", "أخرى"

    class Action(models.TextChoices):
        CREATE = "CREATE", "إنشاء"
        UPDATE = "UPDATE", "تعديل"
        DELETE = "DELETE", "حذف"
        ACTIVATE = "ACTIVATE", "تفعيل"
        DEACTIVATE = "DEACTIVATE", "تعطيل"
        TRANSFER = "TRANSFER", "نقل"
        APPROVE = "APPROVE", "اعتماد"
        PUBLISH = "PUBLISH", "نشر"
        CHANGE_ROLE = "CHANGE_ROLE", "تغيير دور"
        RESET_PASSWORD = "RESET_PASSWORD", "إعادة تعيين كلمة المرور"
        CLOSE = "CLOSE", "إغلاق"
        END = "END", "إنهاء"
        REOPEN = "REOPEN", "إعادة فتح"
        CANCEL = "CANCEL", "إلغاء"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
        null=True,
        blank=True,
    )
    actor_display = models.CharField(max_length=255)
    module = models.CharField(max_length=20, choices=Module.choices)
    action = models.CharField(max_length=30, choices=Action.choices)
    message = models.TextField()
    target_type = models.CharField(max_length=100)
    target_id = models.CharField(max_length=255)
    target_display = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_logs_audit_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"], name="audit_created_idx"),
            models.Index(fields=["module", "created_at"], name="audit_module_date_idx"),
            models.Index(fields=["action", "created_at"], name="audit_action_date_idx"),
            models.Index(fields=["target_type", "target_id"], name="audit_target_idx"),
        ]

    def __str__(self):
        return self.message
