import uuid

from django.conf import settings
from django.db import models


class Homework(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    teacher_assignment = models.ForeignKey(
        "teaching.TeacherAssignment",
        on_delete=models.PROTECT,
        related_name="homeworks",
    )

    title = models.CharField(
        max_length=200,
    )

    description = models.TextField()

    homework_date = models.DateField()

    due_date = models.DateField()

    attachment = models.FileField(
        upload_to="homework/attachments/",
        null=True,
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_homeworks",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = [
            "-homework_date",
            "-created_at",
        ]

        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    due_date__gte=models.F("homework_date"),
                ),
                name="homework_due_date_not_before_homework_date",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "teacher_assignment",
                    "homework_date",
                ],
            ),
            models.Index(
                fields=[
                    "due_date",
                ],
            ),
        ]

    def __str__(self):
        return self.title
