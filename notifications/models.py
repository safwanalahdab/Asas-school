import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def validate_notification_student_ownership(*, recipient, student):
    if student is None or recipient is None:
        return
    if not student.is_active:
        raise ValidationError(
            {"student": "\u0644\u0627 \u064a\u0645\u0643\u0646 \u0631\u0628\u0637 \u0627\u0644\u0625\u0634\u0639\u0627\u0631 \u0628\u0637\u0627\u0644\u0628 \u063a\u064a\u0631 \u0646\u0634\u0637."}
        )

    from students.models import GuardianStudent

    if not GuardianStudent.objects.filter(
        guardian=recipient,
        student=student,
        is_active=True,
    ).exists():
        raise ValidationError(
            {
                "student": (
                    "\u0627\u0644\u0637\u0627\u0644\u0628 \u063a\u064a\u0631 \u0645\u0631\u062a\u0628\u0637 \u0628\u0648\u0644\u064a \u0627\u0644\u0623\u0645\u0631 \u0627\u0644\u0645\u0633\u062a\u0644\u0645 "
                    "\u0627\u0631\u062a\u0628\u0627\u0637\u064b\u0627 \u0646\u0634\u0637\u064b\u0627."
                )
            }
        )


class Notification(models.Model):
    class NotificationType(models.TextChoices):
        HOMEWORK = "homework", "\u0627\u0644\u0648\u0627\u062c\u0628\u0627\u062a"
        ANNOUNCEMENT = "announcement", "\u0627\u0644\u0625\u0639\u0644\u0627\u0646\u0627\u062a"
        GRADES = "grades", "\u0627\u0644\u0639\u0644\u0627\u0645\u0627\u062a"
        ATTENDANCE = "attendance", "\u0627\u0644\u062d\u0636\u0648\u0631"
        BEHAVIOR = "behavior", "\u0627\u0644\u0633\u0644\u0648\u0643"
        FINANCE = "finance", "\u0627\u0644\u0645\u0627\u0644\u064a\u0629"
        SCHOOL_REQUEST = "school_request", "\u0627\u0644\u0637\u0644\u0628\u0627\u062a \u0627\u0644\u0645\u062f\u0631\u0633\u064a\u0629"
        APPOINTMENT = "appointment", "\u0627\u0644\u0645\u0648\u0627\u0639\u064a\u062f"
        GENERAL = "general", "\u0639\u0627\u0645"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="notifications",
        limit_choices_to={"role": "guardian"},
    )
    notification_type = models.CharField(
        max_length=20,
        choices=NotificationType.choices,
    )
    title = models.CharField(max_length=200)
    body = models.TextField()
    student = models.ForeignKey(
        "students.Student",
        on_delete=models.PROTECT,
        related_name="notifications",
        null=True,
        blank=True,
    )
    resource_type = models.CharField(max_length=50, blank=True, default="")
    resource_id = models.UUIDField(null=True, blank=True)
    event_key = models.CharField(max_length=255, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notifications_notification"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "event_key"],
                condition=models.Q(event_key__isnull=False),
                name="notif_recipient_event_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(is_read=False, read_at__isnull=True)
                    | models.Q(is_read=True, read_at__isnull=False)
                ),
                name="notif_read_state_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(resource_type="", resource_id__isnull=True)
                    | (~models.Q(resource_type="") & models.Q(resource_id__isnull=False))
                ),
                name="notif_resource_pair_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["recipient", "created_at"],
                name="notif_rec_created_idx",
            ),
            models.Index(
                fields=["recipient", "is_read", "created_at"],
                name="notif_rec_read_created_idx",
            ),
        ]

    def clean(self):
        super().clean()
        validate_notification_student_ownership(
            recipient=self.recipient if self.recipient_id else None,
            student=self.student if self.student_id else None,
        )

    def __str__(self):
        return f"{self.recipient} - {self.title}"


class PushDevice(models.Model):
    class Platform(models.TextChoices):
        ANDROID = "android", "Android"
        IOS = "ios", "iOS"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="push_devices",
    )
    installation_id = models.UUIDField(unique=True)
    fcm_token = models.TextField()
    platform = models.CharField(max_length=10, choices=Platform.choices)
    device_name = models.CharField(max_length=150, blank=True, default="")
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notifications_push_device"
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(fcm_token=""),
                name="push_device_token_not_blank",
            ),
            models.UniqueConstraint(
                fields=["fcm_token"],
                condition=models.Q(is_active=True),
                name="push_device_active_token_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "is_active", "last_seen_at"],
                name="push_dev_user_active_seen_idx",
            ),
        ]

    def clean(self):
        super().clean()
        self.fcm_token = self.fcm_token.strip() if self.fcm_token else ""
        self.device_name = self.device_name.strip() if self.device_name else ""
        if not self.fcm_token:
            raise ValidationError({"fcm_token": "FCM token is required."})

    def __str__(self):
        return f"{self.user} - {self.platform} - {self.installation_id}"
