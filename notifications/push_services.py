import logging
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from firebase_admin import messaging

from .firebase_client import get_firebase_app
from .models import Notification, PushDevice


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PushDeliveryResult:
    attempted: int = 0
    sent: int = 0
    failed: int = 0
    disabled: int = 0


def build_notification_message(*, notification, token):
    data = {
        "notification_id": str(notification.id),
        "type": str(notification.notification_type),
        "student_id": str(notification.student_id) if notification.student_id else "",
        "resource_type": str(notification.resource_type or ""),
        "resource_id": str(notification.resource_id) if notification.resource_id else "",
    }
    return messaging.Message(
        notification=messaging.Notification(
            title=notification.title,
            body=notification.body,
        ),
        data=data,
        token=token,
    )


def _unique_token_devices(devices):
    # Active tokens are unique in the database; this only guards against a
    # caller-supplied list sending the same token twice.
    seen, unique = set(), []
    for device in devices:
        if device.fcm_token not in seen:
            seen.add(device.fcm_token)
            unique.append(device)
    return unique


def send_notification_push(notification, *, devices=None):
    """Send to the recipient's active devices.

    ``devices`` lets a batch pass that recipient's preloaded active devices
    (ordered by id) instead of querying them per notification.
    """
    if not settings.FIREBASE_PUSH_ENABLED:
        return PushDeliveryResult()

    recipient = notification.recipient
    if not recipient.is_active or recipient.must_change_password:
        return PushDeliveryResult()

    if devices is None:
        devices = PushDevice.objects.filter(user=recipient, is_active=True).order_by("id")
    devices = _unique_token_devices(devices)
    if not devices:
        return PushDeliveryResult()

    try:
        app = get_firebase_app()
    except Exception as error:
        logger.error(
            "Firebase initialization failed for notification_id=%s error=%s",
            notification.id,
            type(error).__name__,
        )
        return PushDeliveryResult(attempted=len(devices), failed=len(devices))

    sent = failed = disabled = 0
    for device in devices:
        message = build_notification_message(
            notification=notification,
            token=device.fcm_token,
        )
        try:
            messaging.send(message, app=app)
            sent += 1
        except messaging.UnregisteredError as error:
            failed += 1
            disabled += 1
            PushDevice.objects.filter(pk=device.pk, is_active=True).update(
                is_active=False,
                updated_at=timezone.now(),
            )
            logger.warning(
                "Unregistered Firebase target disabled notification_id=%s "
                "device_id=%s error=%s",
                notification.id,
                device.id,
                type(error).__name__,
            )
        except Exception as error:
            failed += 1
            logger.error(
                "Firebase delivery failed notification_id=%s device_id=%s error=%s",
                notification.id,
                device.id,
                type(error).__name__,
            )

    return PushDeliveryResult(
        attempted=len(devices),
        sent=sent,
        failed=failed,
        disabled=disabled,
    )


def safe_send_notification_push(notification_id):
    if not settings.FIREBASE_PUSH_ENABLED:
        return PushDeliveryResult()
    try:
        notification = Notification.objects.select_related("recipient").get(
            pk=notification_id
        )
        return send_notification_push(notification)
    except Notification.DoesNotExist:
        logger.warning(
            "Push notification no longer exists notification_id=%s",
            notification_id,
        )
    except Exception as error:
        logger.error(
            "Unexpected push failure notification_id=%s error=%s",
            notification_id,
            type(error).__name__,
        )
    return PushDeliveryResult(failed=1)


def safe_send_notifications_push(notification_ids):
    """Batch counterpart of safe_send_notification_push.

    Loads the notifications and every recipient's active devices in two
    queries, then sends each notification through send_notification_push.
    A failure on one notification is logged and never stops the rest.
    """
    if not settings.FIREBASE_PUSH_ENABLED or not notification_ids:
        return []
    try:
        notifications = {
            notification.id: notification
            for notification in Notification.objects.select_related("recipient").filter(
                pk__in=notification_ids
            )
        }
        devices_by_user = {}
        for device in PushDevice.objects.filter(
            user_id__in={n.recipient_id for n in notifications.values()},
            is_active=True,
        ).order_by("id"):
            devices_by_user.setdefault(device.user_id, []).append(device)
    except Exception as error:
        logger.error(
            "Unexpected push batch load failure count=%s error=%s",
            len(notification_ids),
            type(error).__name__,
        )
        return [PushDeliveryResult(failed=1) for _ in notification_ids]

    results = []
    for notification_id in notification_ids:
        notification = notifications.get(notification_id)
        if notification is None:
            logger.warning(
                "Push notification no longer exists notification_id=%s",
                notification_id,
            )
            results.append(PushDeliveryResult(failed=1))
            continue
        try:
            results.append(send_notification_push(
                notification,
                devices=devices_by_user.get(notification.recipient_id, []),
            ))
        except Exception as error:
            logger.error(
                "Unexpected push failure notification_id=%s error=%s",
                notification_id,
                type(error).__name__,
            )
            results.append(PushDeliveryResult(failed=1))
    return results


def schedule_notification_push(notification_id):
    # on_commit only defers until commit; the push still runs in this process.
    transaction.on_commit(
        lambda: safe_send_notification_push(notification_id), robust=True,
    )


def schedule_notifications_push(notification_ids):
    """One post-commit callback for a whole fan-out batch."""
    notification_ids = list(notification_ids)
    if notification_ids:
        transaction.on_commit(
            lambda: safe_send_notifications_push(notification_ids), robust=True,
        )
