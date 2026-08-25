import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


SENSITIVE = (
    "password", "temporary_password", "token", "access_token", "refresh",
    "refresh_token", "jwt", "csrf", "cookie", "authorization", "secret",
    "credential",
)


def sanitize(value):
    if isinstance(value, dict):
        return {
            str(key): sanitize(item)
            for key, item in value.items()
            if not any(part in str(key).casefold() for part in SENSITIVE)
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return value


def backfill_business_fields(apps, schema_editor):
    AuditLog = apps.get_model("audit_logs", "AuditLog")
    action_labels = {
        "CREATE": "إنشاء", "UPDATE": "تعديل", "DELETE": "حذف",
        "ACTIVATE": "تفعيل", "DEACTIVATE": "تعطيل", "TRANSFER": "نقل",
        "END": "إنهاء", "REOPEN": "إعادة فتح",
        "RESET_PASSWORD": "إعادة تعيين كلمة المرور",
    }
    module_map = {
        "accounts": "accounts", "students": "students", "academics": "academics",
        "teaching": "academics", "attendance": "attendance", "grades": "grades",
        "finance": "finance",
    }
    for entry in AuditLog.objects.select_related("actor").iterator(chunk_size=500):
        actor = entry.actor
        if actor is None:
            actor_display = "مستخدم سابق"
        else:
            full_name = f"{getattr(actor, 'first_name', '')} {getattr(actor, 'last_name', '')}".strip()
            actor_display = full_name or actor.username or str(actor.pk)
        prefix = (entry.target_type or "").split(".", 1)[0].casefold()
        entry.actor_display = actor_display[:255]
        entry.module = module_map.get(prefix, "other")
        entry.message = f"{action_labels.get(entry.action, entry.action)} - {entry.target_display}"
        entry.metadata = sanitize(entry.metadata or {})
        entry.save(update_fields=["actor_display", "module", "message", "metadata"])


class Migration(migrations.Migration):
    dependencies = [
        ("audit_logs", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.RemoveIndex("auditlog", "audit_actor_idx"),
        migrations.RemoveIndex("auditlog", "audit_resource_idx"),
        migrations.RenameField("auditlog", "resource_type", "target_type"),
        migrations.RenameField("auditlog", "resource_id", "target_id"),
        migrations.RenameField("auditlog", "resource_display", "target_display"),
        migrations.RenameField("auditlog", "changes", "metadata"),
        migrations.AddField("auditlog", "actor_display", models.CharField(max_length=255, null=True)),
        migrations.AddField("auditlog", "module", models.CharField(max_length=20, null=True)),
        migrations.AddField("auditlog", "message", models.TextField(null=True)),
        migrations.AddField("auditlog", "ip_address", models.GenericIPAddressField(blank=True, null=True)),
        migrations.RunPython(backfill_business_fields, migrations.RunPython.noop),
        migrations.AlterField("auditlog", "actor_display", models.CharField(max_length=255)),
        migrations.AlterField("auditlog", "module", models.CharField(choices=[("accounts", "الحسابات"), ("students", "الطلاب"), ("academics", "الشؤون الأكاديمية"), ("attendance", "الحضور"), ("grades", "العلامات"), ("finance", "المالية"), ("other", "أخرى")], max_length=20)),
        migrations.AlterField("auditlog", "message", models.TextField()),
        migrations.AlterField("auditlog", "actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="audit_logs", to=settings.AUTH_USER_MODEL)),
        migrations.AlterField("auditlog", "action", models.CharField(choices=[("CREATE", "إنشاء"), ("UPDATE", "تعديل"), ("DELETE", "حذف"), ("ACTIVATE", "تفعيل"), ("DEACTIVATE", "تعطيل"), ("TRANSFER", "نقل"), ("APPROVE", "اعتماد"), ("PUBLISH", "نشر"), ("CHANGE_ROLE", "تغيير دور"), ("RESET_PASSWORD", "إعادة تعيين كلمة المرور"), ("CLOSE", "إغلاق"), ("END", "إنهاء"), ("REOPEN", "إعادة فتح"), ("CANCEL", "إلغاء")], max_length=30)),
        migrations.AddIndex("auditlog", models.Index(fields=["target_type", "target_id"], name="audit_target_idx")),
        migrations.AlterField("auditlog", "metadata", models.JSONField(blank=True, default=dict)),
        migrations.AddIndex("auditlog", models.Index(fields=["module", "created_at"], name="audit_module_date_idx")),
        migrations.AddIndex("auditlog", models.Index(fields=["action", "created_at"], name="audit_action_date_idx")),
    ]
