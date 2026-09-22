from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("grades", "0003_alter_assessment_options")]

    operations = [
        migrations.AlterModelOptions(
            name="assessment",
            options={
                "ordering": ["-assessment_date", "-created_at"],
                "permissions": [
                    ("correct_published_grades", "تصحيح العلامات المنشورة"),
                    ("publish_grades", "نشر العلامات"),
                    ("create_grade_wide_assessment", "إنشاء تقييم لجميع شعب الصف"),
                ],
            },
        ),
    ]
