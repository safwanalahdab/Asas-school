from django.db import migrations


def backfill_student_health_profiles(apps, schema_editor):
    Student = apps.get_model("students", "Student")
    StudentHealthProfile = apps.get_model("students", "StudentHealthProfile")
    database_alias = schema_editor.connection.alias

    for student in Student.objects.using(database_alias).iterator():
        StudentHealthProfile.objects.using(database_alias).get_or_create(
            student=student
        )


class Migration(migrations.Migration):

    dependencies = [
        (
            "students",
            "0007_guardianstudent_relationship_student_first_name_en_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(
            backfill_student_health_profiles,
            migrations.RunPython.noop,
        ),
    ]
