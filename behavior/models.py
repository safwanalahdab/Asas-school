import uuid

from django.conf import settings
from django.db import models


class BehaviorNote(models.Model):
    class Type(models.TextChoices):
        POSITIVE = "positive", "إيجابية"
        NEGATIVE = "negative", "سلبية"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    enrollment = models.ForeignKey(
        "students.Enrollment",
        on_delete=models.PROTECT,
        related_name="behavior_notes",
    )

    note_type = models.CharField(
        max_length=10,
        choices=Type.choices,
    )

    title = models.CharField(
        max_length=150,
    )

    description = models.TextField()

    occurred_on = models.DateField()

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_behavior_notes",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = [
            "-occurred_on",
            "-created_at",
        ]

    def __str__(self):
        return f"{self.get_note_type_display()} - {self.title}"