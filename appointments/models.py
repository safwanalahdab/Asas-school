import uuid

from django.conf import settings
from django.db import models


class AppointmentRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "قيد الانتظار"
        APPROVED = "approved", "مقبول"
        REJECTED = "rejected", "مرفوض"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    guardian = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="appointment_requests",
        limit_choices_to={
            "role": "guardian",
        },
    )

    requested_date = models.DateField()

    requested_time = models.TimeField(
        null=True,
        blank=True,
    )

    request_reason = models.TextField()

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    decision_reason = models.TextField(
        blank=True,
        default="",
    )

    approval_note = models.TextField(
        blank=True,
        default="",
    )

    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="decided_appointment_requests",
        null=True,
        blank=True,
    )

    decided_at = models.DateTimeField(
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
        db_table = "appointments_request"

        permissions = [
            ("decide_appointment_request", "اتخاذ قرار بشأن طلب موعد"),
        ]

        ordering = [
            "-created_at",
        ]

        indexes = [
            models.Index(
                fields=[
                    "status",
                    "requested_date",
                    "requested_time",
                ],
                name="appt_status_datetime_idx",
            ),
            models.Index(
                fields=[
                    "guardian",
                    "created_at",
                ],
                name="appt_guardian_created_idx",
            ),
        ]

        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="pending",
                        decision_reason="",
                        approval_note="",
                        decided_by__isnull=True,
                        decided_at__isnull=True,
                    )
                    | (
                        models.Q(
                            status="approved",
                            decision_reason="",
                            decided_by__isnull=False,
                            decided_at__isnull=False,
                        )
                    )
                    | (
                        models.Q(
                            status="rejected",
                            approval_note="",
                            decided_by__isnull=False,
                            decided_at__isnull=False,
                        )
                        & ~models.Q(
                            decision_reason="",
                        )
                    )
                ),
                name="appt_decision_state_valid",
            ),
        ]

    def __str__(self):
        return (
            f"{self.guardian} - "
            f"{self.requested_date} - "
            f"{self.get_status_display()}"
        )
