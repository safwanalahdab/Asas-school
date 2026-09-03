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


def send_notification_push(notification):
    if not settings.FIREBASE_PUSH_ENABLED:
        return PushDeliveryResult()

    recipient = notification.recipient
    if not recipient.is_active or recipient.must_change_password:
        return PushDeliveryResult()

    devices = list(
        PushDevice.objects.filter(user=recipient, is_active=True).order_by("id")
    )
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


def schedule_notification_push(notification_id):
    transaction.on_commit(lambda: safe_send_notification_push(notification_id))
