from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0009_backfill_supervisor_account_permissions"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="created_users",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
