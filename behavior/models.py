import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
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


class StudentPointEntry(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    enrollment = models.ForeignKey(
        "students.Enrollment",
        on_delete=models.PROTECT,
        related_name="point_entries",
    )

    points = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(1),
            MaxValueValidator(100),
        ],
    )

    note = models.TextField()

    occurred_on = models.DateField()

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_student_point_entries",
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
            "-id",
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(points__gte=1, points__lte=100),
                name="behavior_spe_points_1_100",
            ),
        ]
        indexes = [
            models.Index(
                fields=["enrollment", "-occurred_on"],
                name="behavior_spe_enr_date_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if self.note is not None and not self.note.strip():
            raise ValidationError(
                {"note": "يجب إدخال سبب واضح لمنح النقاط."}
            )

    def __str__(self):
        return f"الطالب/التسجيل {self.enrollment_id} - {self.points} نقطة"
