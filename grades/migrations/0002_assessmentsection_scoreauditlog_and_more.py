import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def migrate_legacy_grade_scope(apps, schema_editor):
    Assessment = apps.get_model("grades", "Assessment")
    AssessmentSection = apps.get_model("grades", "AssessmentSection")
    StudentScore = apps.get_model("grades", "StudentScore")
    links = []
    for assessment in Assessment.objects.all().iterator():
        links.append(AssessmentSection(
            assessment_id=assessment.id,
            section_id=assessment.section_id,
            status=assessment.status,
            published_by_id=assessment.published_by_id,
            published_at=assessment.published_at,
        ))
    AssessmentSection.objects.bulk_create(links)
    for score in StudentScore.objects.select_related("assessment").all().iterator():
        score.recorded_section_id = score.assessment.section_id
        score.save(update_fields=["recorded_section"])


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0003_remove_stage_model"),
        ("grades", "0001_initial"),
        ("students", "0006_alter_enrollment_usual_arrival_method_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AssessmentSection",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(choices=[("draft", "مسودة"), ("published", "منشور")], default="draft", max_length=20)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("assessment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assessment_sections", to="grades.assessment")),
                ("published_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="published_assessment_sections", to=settings.AUTH_USER_MODEL)),
                ("section", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="assessment_sections", to="academics.section")),
            ],
            options={"db_table": "grades_assessment_section", "ordering": ["section__name"]},
        ),
        migrations.AddField(
            model_name="studentscore", name="recorded_section",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="recorded_student_scores", to="academics.section"),
        ),
        migrations.RunPython(migrate_legacy_grade_scope, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="studentscore", name="recorded_section",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="recorded_student_scores", to="academics.section"),
        ),
        migrations.RemoveConstraint(model_name="assessment", name="gr_assess_publish_consistent"),
        migrations.RemoveIndex(model_name="assessment", name="gr_assess_sec_term_st_idx"),
        migrations.RemoveField(model_name="assessment", name="published_at"),
        migrations.RemoveField(model_name="assessment", name="published_by"),
        migrations.RemoveField(model_name="assessment", name="section"),
        migrations.RemoveField(model_name="assessment", name="status"),
        migrations.AddIndex(model_name="assessment", index=models.Index(fields=["grade_subject", "term"], name="gr_assess_sub_term_idx")),
        migrations.AddIndex(model_name="assessmentsection", index=models.Index(fields=["section", "status"], name="gr_assess_sec_st_idx")),
        migrations.AddConstraint(model_name="assessmentsection", constraint=models.UniqueConstraint(fields=("assessment", "section"), name="gr_assess_section_unique")),
        migrations.AddConstraint(
            model_name="assessmentsection",
            constraint=models.CheckConstraint(
                condition=models.Q(models.Q(published_at__isnull=True, published_by__isnull=True, status="draft"), models.Q(published_at__isnull=False, published_by__isnull=False, status="published"), _connector="OR"),
                name="gr_assess_sec_publish_consistent",
            ),
        ),
        migrations.CreateModel(
            name="ScoreAuditLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("old_score", models.DecimalField(blank=True, decimal_places=2, max_digits=7, null=True)),
                ("new_score", models.DecimalField(blank=True, decimal_places=2, max_digits=7, null=True)),
                ("source", models.CharField(choices=[("api", "واجهة API"), ("admin", "لوحة الإدارة")], max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="score_audit_logs", to=settings.AUTH_USER_MODEL)),
                ("assessment", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="score_audit_logs", to="grades.assessment")),
                ("enrollment", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="score_audit_logs", to="students.enrollment")),
                ("recorded_section", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="score_audit_logs", to="academics.section")),
            ],
            options={"db_table": "grades_score_audit_log", "ordering": ["-created_at"]},
        ),
        migrations.AddIndex(model_name="scoreauditlog", index=models.Index(fields=["assessment", "enrollment", "created_at"], name="gr_score_audit_hist_idx")),
    ]
