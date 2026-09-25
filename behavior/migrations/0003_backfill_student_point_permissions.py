from django.db import migrations


POINT_PERMISSIONS = (
    ("add_studentpointentry", "Can add student point entry"),
    ("change_studentpointentry", "Can change student point entry"),
    ("delete_studentpointentry", "Can delete student point entry"),
    ("view_studentpointentry", "Can view student point entry"),
)


def add_existing_point_permissions(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    User = apps.get_model("accounts", "User")
    database_alias = schema_editor.connection.alias

    content_type, _ = ContentType.objects.using(database_alias).get_or_create(
        app_label="behavior",
        model="studentpointentry",
    )
    permissions = []
    for codename, name in POINT_PERMISSIONS:
        permission, _ = Permission.objects.using(database_alias).get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={"name": name},
        )
        permissions.append(permission)

    for user in User.objects.using(database_alias).filter(
        role__in=("school_admin", "supervisor"),
    ).iterator():
        user.user_permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("accounts", "0009_backfill_supervisor_account_permissions"),
        ("behavior", "0002_studentpointentry"),
    ]

    operations = [
        migrations.RunPython(
            add_existing_point_permissions,
            migrations.RunPython.noop,
        ),
    ]
