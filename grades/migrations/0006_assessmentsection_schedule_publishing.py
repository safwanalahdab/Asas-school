import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("grades", "0005_backfill_published_grade_correction_permission"),
    ]

    operations = [
        migrations.AddField(
            model_name="assessmentsection",
            name="schedule_status",
            field=models.CharField(
                choices=[("draft", "مسودة"), ("published", "منشور")],
                default="draft",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="assessmentsection",
            name="schedule_published_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="schedule_published_assessment_sections",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="assessmentsection",
            name="schedule_published_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="assessmentsection",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        schedule_published_at__isnull=True,
                        schedule_published_by__isnull=True,
                        schedule_status="draft",
                    ),
                    models.Q(
                        schedule_published_at__isnull=False,
                        schedule_published_by__isnull=False,
                        schedule_status="published",
                    ),
                    _connector="OR",
                ),
                name="gr_assess_sched_consistent",
            ),
        ),
        migrations.AddIndex(
            model_name="assessmentsection",
            index=models.Index(
                fields=["section", "schedule_status"],
                name="gr_assess_sec_sched_idx",
            ),
        ),
    ]
