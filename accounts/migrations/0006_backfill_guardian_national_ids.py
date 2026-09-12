from django.db import migrations


def backfill_guardian_national_ids(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    database_alias = schema_editor.connection.alias

    guardians = User.objects.using(database_alias).filter(
        role="guardian",
        national_id__isnull=True,
    )
    for guardian in guardians.iterator():
        username = guardian.username
        if username.isascii() and username.isdigit():
            User.objects.using(database_alias).filter(pk=guardian.pk).update(
                national_id=username
            )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_user_national_id_user_phone_number"),
    ]

    operations = [
        migrations.RunPython(
            backfill_guardian_national_ids,
            migrations.RunPython.noop,
        ),
    ]
