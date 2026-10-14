import django.utils.timezone
from django.db import migrations, models


PUSH_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('sent', 'Sent'),
    ('failed', 'Failed'),
    ('skipped', 'Skipped'),
    ('expired', 'Expired'),
]


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0002_pushdevice'),
    ]

    operations = [
        # db_default stays on the NOT NULL columns. Existing rows, and rows
        # inserted later by code that predates these columns (after a
        # rollback), become "skipped" and are never sent by the worker.
        # The ORM still writes the model default ("pending") for new rows.
        migrations.AddField(
            model_name='notification',
            name='push_status',
            field=models.CharField(
                choices=PUSH_STATUS_CHOICES, db_default='skipped', default='pending', max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='notification',
            name='push_attempts',
            field=models.PositiveSmallIntegerField(db_default=0, default=0),
        ),
        migrations.AddField(
            model_name='notification',
            name='push_next_attempt_at',
            field=models.DateTimeField(blank=True, default=django.utils.timezone.now, null=True),
        ),
        migrations.AddField(
            model_name='notification',
            name='push_locked_until',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='notification',
            name='push_lease_token',
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='notification',
            name='push_sent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='notification',
            name='push_last_error',
            field=models.CharField(blank=True, db_default='', default='', max_length=100),
        ),
        migrations.AddField(
            model_name='notification',
            name='push_delivered_device_ids',
            field=models.JSONField(blank=True, db_default=[], default=list),
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(
                condition=models.Q(('push_status', 'pending')),
                fields=['push_next_attempt_at'],
                name='notif_push_pending_due_idx',
            ),
        ),
    ]
