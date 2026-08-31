import uuid

from django.conf import settings
from django.db import models

from students.models import Student


class SchoolRequest(models.Model):
    class RequestType(models.TextChoices):
        COMPLAINT = "complaint", "شكوى"
        SUGGESTION = "suggestion", "اقتراح"
        INQUIRY = "inquiry", "استفسار"

    class Status(models.TextChoices):
        NEW = "new", "جديد"
        ANSWERED = "answered", "تمت الإجابة"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    request_type = models.CharField(
        max_length=20,
        choices=RequestType.choices,
    )

    details = models.TextField()

    guardian = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="school_requests",
        limit_choices_to={
            "role": "guardian",
        },
    )

    student = models.ForeignKey(
        Student,
        on_delete=models.PROTECT,
        related_name="school_requests",
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
    )

    school_response = models.TextField(
        blank=True,
        default="",
    )

    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="handled_school_requests",
        null=True,
        blank=True,
    )

    answered_at = models.DateTimeField(
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
        db_table = "school_requests_request"

        ordering = [
            "-created_at",
        ]

        indexes = [
            models.Index(
                fields=[
                    "status",
                    "created_at",
                ],
            ),
            models.Index(
                fields=[
                    "request_type",
                    "created_at",
                ],
            ),
            models.Index(
                fields=[
                    "guardian",
                    "created_at",
                ],
            ),
        ]

    def __str__(self):
        return f"{self.get_request_type_display()}"