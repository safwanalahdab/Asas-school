from django.db import migrations


PERMISSION_CODENAME = "view_student_profile"
PERMISSION_NAME = "عرض الملف الشامل للطالب"
TARGET_ROLES = ("school_admin", "secretariat", "supervisor")


def add_student_profile_permission(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    User = apps.get_model("accounts", "User")

    content_type, _ = ContentType.objects.get_or_create(
        app_label="students",
        model="student",
    )
    permission, _ = Permission.objects.get_or_create(
        content_type=content_type,
        codename=PERMISSION_CODENAME,
        defaults={"name": PERMISSION_NAME},
    )
    if permission.name != PERMISSION_NAME:
        permission.name = PERMISSION_NAME
        permission.save(update_fields=["name"])

    for user in User.objects.filter(role__in=TARGET_ROLES).iterator():
        user.user_permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("accounts", "0007_alter_user_options"),
        ("students", "0009_alter_student_options"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="student",
            options={
                "ordering": ["first_name", "last_name"],
                "permissions": [
                    ("register_student", "تسجيل طالب"),
                    ("transfer_student", "نقل طالب بين الشعب"),
                    ("view_student_profile", "عرض الملف الشامل للطالب"),
                ],
            },
        ),
        migrations.RunPython(
            add_student_profile_permission,
            migrations.RunPython.noop,
        ),
    ]
