from django.db import migrations


PERMISSION_CODENAME = "publish_assessment_schedule"
PERMISSION_NAME = "نشر مواعيد الامتحانات"


def grant_existing_staff_permission(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    User = apps.get_model("accounts", "User")
    database_alias = schema_editor.connection.alias

    content_type, _ = ContentType.objects.using(database_alias).get_or_create(
        app_label="grades",
        model="assessment",
    )
    permission, _ = Permission.objects.using(database_alias).get_or_create(
        content_type=content_type,
        codename=PERMISSION_CODENAME,
        defaults={"name": PERMISSION_NAME},
    )
    for user in User.objects.using(database_alias).filter(
        role__in=("school_admin", "supervisor"),
    ).iterator():
        user.user_permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("accounts", "0009_backfill_supervisor_account_permissions"),
        ("grades", "0006_assessmentsection_schedule_publishing"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="assessment",
            options={
                "ordering": ["-assessment_date", "-created_at"],
                "permissions": [
                    ("correct_published_grades", "تصحيح العلامات المنشورة"),
                    ("publish_grades", "نشر العلامات"),
                    ("publish_assessment_schedule", "نشر مواعيد الامتحانات"),
                    ("create_grade_wide_assessment", "إنشاء تقييم لجميع شعب الصف"),
                ],
            },
        ),
        migrations.RunPython(
            grant_existing_staff_permission,
            migrations.RunPython.noop,
        ),
    ]
