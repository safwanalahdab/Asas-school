from django.db import migrations


def give_existing_supervisors_all_scope(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    SupervisorScope = apps.get_model("academics", "SupervisorScope")
    database_alias = schema_editor.connection.alias

    supervisor_ids = (
        User.objects.using(database_alias)
        .filter(role="supervisor")
        .values_list("pk", flat=True)
    )
    for supervisor_id in supervisor_ids.iterator():
        SupervisorScope.objects.using(database_alias).get_or_create(
            supervisor_id=supervisor_id,
            defaults={"scope_type": "all"},
        )


class Migration(migrations.Migration):
    dependencies = [
        (
            "academics",
            "0004_supervisorscope_supervisorscopestage_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(
            give_existing_supervisors_all_scope,
            migrations.RunPython.noop,
        ),
    ]
