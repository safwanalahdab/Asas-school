from django.db import migrations, models
from django.db.models import Count
from django.db.models.functions import Lower


def ensure_no_case_insensitive_duplicate_usernames(apps, schema_editor):
    """
    Refuse to add the constraint while usernames differ only by letter case.

    Merging or renaming accounts is a business decision, so this migration
    never changes data. The error lists user ids only, never usernames.
    """
    User = apps.get_model("accounts", "User")
    users = User.objects.using(schema_editor.connection.alias).annotate(
        username_key=Lower("username")
    )
    duplicate_keys = list(
        users.order_by()
        .values("username_key")
        .annotate(total=Count("pk"))
        .filter(total__gt=1)
        .values_list("username_key", flat=True)
    )
    if not duplicate_keys:
        return

    groups = [
        sorted(
            str(pk)
            for pk in users.filter(username_key=key).values_list("pk", flat=True)
        )
        for key in duplicate_keys
    ]
    groups.sort()
    raise RuntimeError(
        "Cannot add unique_user_username_case_insensitive: found "
        f"{len(groups)} group(s) of accounts whose usernames differ only by "
        "letter case. Resolve them manually before running this migration; "
        "no account was changed. User ids per group: "
        + "; ".join(f"[{', '.join(ids)}]" for ids in groups)
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0010_user_created_by"),
    ]

    operations = [
        migrations.RunPython(
            ensure_no_case_insensitive_duplicate_usernames,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(
                Lower("username"),
                name="unique_user_username_case_insensitive",
            ),
        ),
    ]
