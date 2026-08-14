import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("action", models.CharField(choices=[("CREATE", "إنشاء"), ("UPDATE", "تعديل"), ("DELETE", "حذف"), ("ACTIVATE", "تفعيل"), ("DEACTIVATE", "تعطيل"), ("TRANSFER", "نقل"), ("END", "إنهاء"), ("REOPEN", "إعادة فتح"), ("RESET_PASSWORD", "إعادة تعيين كلمة المرور")], max_length=30)),
                ("resource_type", models.CharField(max_length=100)),
                ("resource_id", models.CharField(max_length=255)),
                ("resource_display", models.CharField(max_length=255)),
                ("changes", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="audit_logs", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "audit_logs_audit_log", "ordering": ["-created_at"]},
        ),
        migrations.AddIndex(model_name="auditlog", index=models.Index(fields=["actor"], name="audit_actor_idx")),
        migrations.AddIndex(model_name="auditlog", index=models.Index(fields=["resource_type", "resource_id"], name="audit_resource_idx")),
        migrations.AddIndex(model_name="auditlog", index=models.Index(fields=["created_at"], name="audit_created_idx")),
    ]
