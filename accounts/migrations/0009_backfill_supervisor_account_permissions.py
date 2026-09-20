from django.db import migrations


SUPERVISOR_ACCOUNT_PERMISSIONS = (
    ("change_user", "تعديل مستخدم"),
    ("reset_user_password", "إعادة تعيين كلمة مرور المستخدم"),
    ("set_user_active", "تغيير حالة حساب المستخدم"),
)


def add_supervisor_account_permissions(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    User = apps.get_model("accounts", "User")
    database_alias = schema_editor.connection.alias

    content_type, _ = ContentType.objects.using(database_alias).get_or_create(
        app_label="accounts",
        model="user",
    )
    permissions = []
    for codename, name in SUPERVISOR_ACCOUNT_PERMISSIONS:
        permission, _ = Permission.objects.using(database_alias).get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={"name": name},
        )
        permissions.append(permission)

    for supervisor in User.objects.using(database_alias).filter(
        role="supervisor"
    ).iterator():
        supervisor.user_permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("accounts", "0008_alter_user_role"),
    ]

    operations = [
        migrations.RunPython(
            add_supervisor_account_permissions,
            migrations.RunPython.noop,
        ),
    ]
