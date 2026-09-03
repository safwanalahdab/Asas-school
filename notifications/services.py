import uuid

from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Notification, validate_notification_student_ownership


def _validate_recipient(recipient):
    if recipient is None or getattr(recipient, "pk", None) is None:
        raise ValidationError({"recipient": "\u0648\u0644\u064a \u0627\u0644\u0623\u0645\u0631 \u0627\u0644\u0645\u0633\u062a\u0644\u0645 \u0645\u0637\u0644\u0648\u0628."})
    if not recipient.is_active:
        raise ValidationError({"recipient": "\u0648\u0644\u064a \u0627\u0644\u0623\u0645\u0631 \u0627\u0644\u0645\u0633\u062a\u0644\u0645 \u063a\u064a\u0631 \u0646\u0634\u0637."})
    if recipient.role != recipient.Role.GUARDIAN:
        raise ValidationError({"recipient": "\u064a\u062c\u0628 \u0623\u0646 \u064a\u0643\u0648\u0646 \u0645\u0633\u062a\u0644\u0645 \u0627\u0644\u0625\u0634\u0639\u0627\u0631 \u0648\u0644\u064a \u0623\u0645\u0631."})


def _normalize_resource_pair(*, resource_type, resource_id):
    if not isinstance(resource_type, str):
        raise ValidationError({"resource_type": "\u0646\u0648\u0639 \u0627\u0644\u0645\u0648\u0631\u062f \u064a\u062c\u0628 \u0623\u0646 \u064a\u0643\u0648\u0646 \u0646\u0635\u064b\u0627."})

    resource_type = resource_type.strip()
    if not resource_type and resource_id is None:
        return "", None
    if not resource_type or resource_id is None:
        raise ValidationError(
            {"resource": "\u064a\u062c\u0628 \u0625\u0631\u0633\u0627\u0644 resource_type \u0648resource_id \u0645\u0639\u064b\u0627."}
        )
    try:
        resource_id = uuid.UUID(str(resource_id))
    except (TypeError, ValueError, AttributeError):
        raise ValidationError({"resource_id": "resource_id \u064a\u062c\u0628 \u0623\u0646 \u064a\u0643\u0648\u0646 UUID \u0635\u0627\u0644\u062d\u064b\u0627."})
    return resource_type, resource_id


def create_notification(
    *,
    recipient,
    notification_type,
    title,
    body,
    student=None,
    resource_type="",
    resource_id=None,
    event_key=None,
):
    _validate_recipient(recipient)
    if notification_type not in Notification.NotificationType.values:
        raise ValidationError({"notification_type": "\u0646\u0648\u0639 \u0627\u0644\u0625\u0634\u0639\u0627\u0631 \u063a\u064a\u0631 \u0635\u0627\u0644\u062d."})
    if not isinstance(title, str) or not title.strip():
        raise ValidationError({"title": "\u0639\u0646\u0648\u0627\u0646 \u0627\u0644\u0625\u0634\u0639\u0627\u0631 \u0645\u0637\u0644\u0648\u0628."})
    if not isinstance(body, str) or not body.strip():
        raise ValidationError({"body": "\u0646\u0635 \u0627\u0644\u0625\u0634\u0639\u0627\u0631 \u0645\u0637\u0644\u0648\u0628."})

    validate_notification_student_ownership(recipient=recipient, student=student)
    resource_type, resource_id = _normalize_resource_pair(
        resource_type=resource_type,
        resource_id=resource_id,
    )
    values = {
        "notification_type": notification_type,
        "title": title.strip(),
        "body": body.strip(),
        "student": student,
        "resource_type": resource_type,
        "resource_id": resource_id,
    }
    candidate = Notification(recipient=recipient, event_key=event_key, **values)
    candidate.full_clean(validate_unique=False, validate_constraints=False)

    if event_key is None:
        candidate.save()
        from .push_services import schedule_notification_push

        schedule_notification_push(candidate.id)
        return candidate, True

    notification, created = Notification.objects.get_or_create(
        recipient=recipient,
        event_key=event_key,
        defaults=values,
    )
    if created:
        from .push_services import schedule_notification_push

        schedule_notification_push(notification.id)
    return notification, created


def mark_notification_as_read(notification):
    if notification.is_read:
        return notification

    now = timezone.now()
    notification.is_read = True
    notification.read_at = now
    notification.updated_at = now
    notification.save(update_fields=["is_read", "read_at", "updated_at"])
    return notification


def mark_all_notifications_as_read(*, recipient):
    now = timezone.now()
    return Notification.objects.filter(
        recipient=recipient,
        is_read=False,
    ).update(
        is_read=True,
        read_at=now,
        updated_at=now,
    )
