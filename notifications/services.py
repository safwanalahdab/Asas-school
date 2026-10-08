import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
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
    _validate_content(notification_type=notification_type, title=title, body=body)

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


def _validate_content(*, notification_type, title, body):
    if notification_type not in Notification.NotificationType.values:
        raise ValidationError({"notification_type": "نوع الإشعار غير صالح."})
    if not isinstance(title, str) or not title.strip():
        raise ValidationError({"title": "عنوان الإشعار مطلوب."})
    if not isinstance(body, str) or not body.strip():
        raise ValidationError({"body": "نص الإشعار مطلوب."})


def create_notifications(specs):
    """Fan-out variant of create_notification for many recipients at once.

    Each spec takes create_notification's keyword arguments. Validation,
    event_key idempotency and push-after-commit match create_notification,
    but lookups and inserts run in a constant number of queries. Returns
    ``(notification, created)`` pairs in spec order. Any spec failing the
    batched checks is re-validated through the single path so the raised
    error is exactly the one create_notification would raise.
    """
    specs = [dict(spec) for spec in specs]
    if not specs:
        return []

    recipient_ids = {
        spec["recipient"].pk for spec in specs
        if spec.get("recipient") is not None and getattr(spec["recipient"], "pk", None) is not None
    }
    student_ids = {spec["student"].pk for spec in specs if spec.get("student") is not None}
    # ForeignKey.validate in full_clean checks the recipient row with limit_choices_to.
    valid_recipient_ids = set(
        Notification._meta.get_field("recipient").remote_field.model._base_manager.filter(
            pk__in=recipient_ids, role="guardian",
        ).values_list("pk", flat=True)
    )
    owned_pairs = set()
    if student_ids:
        from students.models import GuardianStudent

        owned_pairs = set(
            GuardianStudent.objects.filter(
                guardian_id__in=recipient_ids, student_id__in=student_ids, is_active=True,
            ).values_list("guardian_id", "student_id")
        )

    candidates = []
    for spec in specs:
        recipient, student = spec.get("recipient"), spec.get("student")
        _validate_recipient(recipient)
        _validate_content(
            notification_type=spec.get("notification_type"),
            title=spec.get("title"),
            body=spec.get("body"),
        )
        if student is not None and (
            not student.is_active or (recipient.pk, student.pk) not in owned_pairs
        ):
            validate_notification_student_ownership(recipient=recipient, student=student)
        resource_type, resource_id = _normalize_resource_pair(
            resource_type=spec.get("resource_type", ""),
            resource_id=spec.get("resource_id"),
        )
        candidate = Notification(
            recipient=recipient,
            event_key=spec.get("event_key"),
            notification_type=spec["notification_type"],
            title=spec["title"].strip(),
            body=spec["body"].strip(),
            student=student,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        try:
            candidate.clean_fields(exclude=["recipient", "student"])
            if recipient.pk not in valid_recipient_ids:
                raise ValidationError({"recipient": "invalid"})
        except ValidationError:
            # Reproduce create_notification's exact error.
            candidate.full_clean(validate_unique=False, validate_constraints=False)
        candidates.append(candidate)

    keyed = [c for c in candidates if c.event_key is not None]
    existing = {}
    if keyed:
        for notification in Notification.objects.filter(
            recipient_id__in={c.recipient_id for c in keyed},
            event_key__in={c.event_key for c in keyed},
        ):
            existing[(notification.recipient_id, notification.event_key)] = notification

    results, new = [], []
    for candidate in candidates:
        key = (candidate.recipient_id, candidate.event_key)
        if candidate.event_key is not None and key in existing:
            results.append((existing[key], False))
            continue
        if candidate.event_key is not None:
            # A repeated (recipient, event_key) in this batch reuses the first row.
            existing[key] = candidate
        new.append(candidate)
        results.append((candidate, True))

    if new:
        try:
            with transaction.atomic():
                Notification.objects.bulk_create(new)
        except IntegrityError:
            # A concurrent writer inserted one of these events; fall back to
            # get_or_create per spec, which resolves races exactly as before.
            return [create_notification(**spec) for spec in specs]

        from .push_services import schedule_notifications_push

        schedule_notifications_push([notification.id for notification in new])
    return results


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
