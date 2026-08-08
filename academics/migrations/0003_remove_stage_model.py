from django.db import migrations, models


STAGE_CHOICES = [
    ("kindergarten", "الروضة"),
    ("primary", "الابتدائية"),
    ("preparatory", "الإعدادية"),
    ("secondary", "الثانوية"),
]


def copy_stage_codes(apps, schema_editor):
    GradeLevel = apps.get_model("academics", "GradeLevel")
    database_alias = schema_editor.connection.alias
    grade_levels = GradeLevel.objects.using(database_alias).select_related("stage")
    for grade_level in grade_levels.iterator():
        grade_level.stage_value = grade_level.stage.code
        grade_level.save(using=database_alias, update_fields=["stage_value"])


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0002_alter_term_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="gradelevel",
            name="stage_value",
            field=models.CharField(
                choices=STAGE_CHOICES,
                max_length=40,
                null=True,
            ),
        ),
        migrations.RunPython(copy_stage_codes, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="gradelevel",
            name="academics_grade_unique_name_per_stage",
        ),
        migrations.RemoveField(
            model_name="gradelevel",
            name="stage",
        ),
        migrations.RenameField(
            model_name="gradelevel",
            old_name="stage_value",
            new_name="stage",
        ),
        migrations.AlterField(
            model_name="gradelevel",
            name="stage",
            field=models.CharField(choices=STAGE_CHOICES, max_length=40),
        ),
        migrations.AddConstraint(
            model_name="gradelevel",
            constraint=models.UniqueConstraint(
                fields=("stage", "name"),
                name="academics_grade_unique_name_per_stage",
            ),
        ),
        migrations.DeleteModel(name="Stage"),
        migrations.AlterModelOptions(
            name="term",
            options={"ordering": ["-academic_year__start_date", "number"]},
        ),
        migrations.AlterModelTable(
            name="term",
            table="academics_term",
        ),
        migrations.AddConstraint(
            model_name="term",
            constraint=models.CheckConstraint(
                condition=models.Q(number__in=[1, 2]),
                name="academics_term_valid_number",
            ),
        ),
        migrations.AddConstraint(
            model_name="term",
            constraint=models.CheckConstraint(
                condition=models.Q(end_date__gt=models.F("start_date")),
                name="academics_term_end_after_start",
            ),
        ),
        migrations.AddConstraint(
            model_name="term",
            constraint=models.CheckConstraint(
                condition=models.Q(status__in=["draft", "active", "closed"]),
                name="academics_term_valid_status",
            ),
        ),
        migrations.AddConstraint(
            model_name="term",
            constraint=models.UniqueConstraint(
                fields=("academic_year", "number"),
                name="academics_term_unique_number_per_year",
            ),
        ),
        migrations.AddConstraint(
            model_name="term",
            constraint=models.UniqueConstraint(
                condition=models.Q(status="active"),
                fields=("academic_year",),
                name="academics_term_single_active_per_year",
            ),
        ),
    ]
