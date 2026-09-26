from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("students", "0011_studentimportjob_studentimportrow_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="enrollment",
            options={
                "ordering": ["-enrollment_date", "-created_at"],
                "permissions": [
                    (
                        "correct_enrollment_placement",
                        "تصحيح شعبة تسجيل الطالب",
                    ),
                ],
            },
        ),
        migrations.AddField(
            model_name="studentauditlog",
            name="reason",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AlterField(
            model_name="studentauditlog",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("section_transfer", "نقل بين الشعب"),
                    ("placement_correction", "تصحيح الشعبة"),
                ],
                max_length=50,
            ),
        ),
    ]
