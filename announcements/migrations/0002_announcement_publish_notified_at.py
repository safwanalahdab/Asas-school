from django.db import migrations, models
from django.utils import timezone


def mark_published_announcements_notified(apps, schema_editor):
    # Announcements already published were notified when they were created,
    # or it is too late to notify them now. Only future ones stay due.
    Announcement = apps.get_model("announcements", "Announcement")
    Announcement.objects.using(schema_editor.connection.alias).filter(
        publish_date__lte=timezone.localdate(),
        publish_notified_at__isnull=True,
    ).update(publish_notified_at=timezone.now())


class Migration(migrations.Migration):

    dependencies = [
        ('announcements', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='announcement',
            name='publish_notified_at',
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddIndex(
            model_name='announcement',
            index=models.Index(condition=models.Q(('publish_notified_at__isnull', True)), fields=['publish_date'], name='announce_notify_due_idx'),
        ),
        migrations.RunPython(
            mark_published_announcements_notified,
            migrations.RunPython.noop,
        ),
    ]
