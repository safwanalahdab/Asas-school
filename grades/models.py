import uuid

from django.conf import settings
from django.db import models

from academics.models import (
    GradeSubject,
    Section,
    Term,
)
from students.models import Enrollment


class Assessment(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "مسودة"
        PUBLISHED = "published", "منشور"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    section = models.ForeignKey(
        Section,
        on_delete=models.PROTECT,
        related_name="assessments",
    )

    grade_subject = models.ForeignKey(
        GradeSubject,
        on_delete=models.PROTECT,
        related_name="assessments",
    )

    term = models.ForeignKey(
        Term,
        on_delete=models.PROTECT,
        related_name="assessments",
    )

    title = models.CharField(
        max_length=150,
    )

    max_score = models.DecimalField(
        max_digits=7,
        decimal_places=2,
    )

    assessment_date = models.DateField()

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_assessments",
    )

    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="published_assessments",
        null=True,
        blank=True,
    )

    published_at = models.DateTimeField(
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
        db_table = "grades_assessment"

        ordering = [
            "-assessment_date",
            "-created_at",
        ]

        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    max_score__gt=0,
                ),
                name="gr_assess_max_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="draft",
                        published_by__isnull=True,
                        published_at__isnull=True,
                    )
                    | models.Q(
                        status="published",
                        published_by__isnull=False,
                        published_at__isnull=False,
                    )
                ),
                name="gr_assess_publish_consistent",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "section",
                    "term",
                    "status",
                ],
                name="gr_assess_sec_term_st_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.title} - "
            f"{self.grade_subject.subject} - "
            f"{self.section}"
        )


class StudentScore(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    assessment = models.ForeignKey(
        Assessment,
        on_delete=models.PROTECT,
        related_name="scores",
    )

    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.PROTECT,
        related_name="assessment_scores",
    )

    score = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_student_scores",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "grades_student_score"

        ordering = [
            "-updated_at",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "assessment",
                    "enrollment",
                ],
                name="gr_score_unique_assess_enr",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        score__isnull=True,
                    )
                    | models.Q(
                        score__gte=0,
                    )
                ),
                name="gr_score_nonnegative",
            ),
        ]

    def __str__(self):
        return (
            f"{self.enrollment.student} - "
            f"{self.assessment} - "
            f"{self.score}"
        )