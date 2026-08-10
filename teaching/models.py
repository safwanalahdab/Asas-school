import uuid

from django.conf import settings
from django.db import models

from academics.models import GradeSubject, Section


class TeacherAssignment(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="teaching_assignments",
    )

    grade_subject = models.ForeignKey(
        GradeSubject,
        on_delete=models.PROTECT,
        related_name="teacher_assignments",
    )

    section = models.ForeignKey(
        Section,
        on_delete=models.PROTECT,
        related_name="teacher_assignments",
    )

    start_date = models.DateField()

    end_date = models.DateField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "teaching_teacher_assignment"

        ordering = [
            "-start_date",
            "-created_at",
        ]

        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(end_date__isnull=True)
                    | models.Q(
                        end_date__gte=models.F("start_date"),
                    )
                ),
                name="teaching_assignment_end_not_before_start",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "teacher",
                    "start_date",
                ],
                name="teaching_teacher_start_idx",
            ),
            models.Index(
                fields=[
                    "grade_subject",
                    "section",
                ],
                name="teaching_subject_section_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.teacher} - "
            f"{self.grade_subject.subject} - "
            f"{self.section}"
        )