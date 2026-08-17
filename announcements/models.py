import uuid

from django.conf import settings
from django.db import models

from academics.models import GradeLevel, Section


class Announcement(models.Model):
    class Scope(models.TextChoices):
        ALL = "all", "جميع المدرسة"
        GRADES = "grades", "صفوف محددة"
        SECTIONS = "sections", "شعب محددة"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    scope = models.CharField(
        max_length=20,
        choices=Scope.choices,
    )

    grade_levels = models.ManyToManyField(
        GradeLevel,
        related_name="announcements",
        blank=True,
    )

    sections = models.ManyToManyField(
        Section,
        related_name="announcements",
        blank=True,
    )

    title = models.CharField(
        max_length=200,
    )

    content = models.TextField()

    publish_date = models.DateField()

    expiry_date = models.DateField(
        null=True,
        blank=True,
    )

    attachment = models.FileField(
        upload_to="announcements/attachments/",
        null=True,
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_announcements",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )