import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import DatabaseError
from django.utils import timezone
from firebase_admin import exceptions as firebase_exceptions
from firebase_admin import messaging

from .firebase_client import get_firebase_app
from .models import Notification, PushDevice


logger = logging.getLogger(__name__)

# Delay before the next attempt after the 1st, 2nd, ... failed attempt; the
# last delay repeats when PUSH_MAX_ATTEMPTS allows more attempts than this.
PUSH_RETRY_DELAYS = (
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=10),
    timedelta(minutes=30),
    timedelta(hours=2),
)

# Firebase will never accept this token again, so the device is disabled.
DEAD_TOKEN_ERRORS = (messaging.UnregisteredError, messaging.SenderIdMismatchError)
# Retrying cannot deliver to this device. Checked before CONFIGURATION_ERRORS
# because SenderIdMismatchError subclasses PermissionDeniedError.
PERMANENT_ERRORS = DEAD_TOKEN_ERRORS + (firebase_exceptions.InvalidArgumentError,)
# Retried, but they mean the server credentials or project setup are broken.
CONFIGURATION_ERRORS = (
    messaging.ThirdPartyAuthError,
    firebase_exceptions.PermissionDeniedError,
    firebase_exceptions.UnauthenticatedError,
)


@dataclass(frozen=True)
class PushAttemptResult:
    """New push state for one claimed notification; the worker stores it."""

    notification_id: object
    status: str
    attempts: int
    delivered_device_ids: list
    next_attempt_at: datetime | None = None
    sent_at: datetime | None = None
    error: str = ""


@dataclass
class _Attempt:
    notification: Notification
    targets: list
    delivered_device_ids: list
    permanent_error: str = ""
    transient_error: str = ""


def build_notification_message(*, notification, token):
    data = {
        "notification_id": str(notification.id),
        "type": str(notification.notification_type),
        "student_id": str(notification.student_id) if notification.student_id else "",
        "resource_type": str(notification.resource_type or ""),
        "resource_id": str(notification.resource_id) if notification.resource_id else "",
    }
    # Collapse keys make a re-sent notification replace the shown one.
    collapse_id = str(notification.id)
    return messaging.Message(
        notification=messaging.Notification(
            title=notification.title,
            body=notification.body,
        ),
        data=data,
        android=messaging.AndroidConfig(
            collapse_key=collapse_id,
            notification=messaging.AndroidNotification(tag=collapse_id),
        ),
        apns=messaging.APNSConfig(headers={"apns-collapse-id": collapse_id}),
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


def send_claimed_notifications(notifications):
    """Try one push attempt for each claimed notification.

    Notifications must have ``recipient`` loaded. All recipients' active
    devices are read in one query, devices that already received the
    notification are skipped, and messages go out through
    ``messaging.send_each`` in chunks of PUSH_SEND_CHUNK_SIZE. Apart from
    disabling dead devices nothing is written; results come back in input
    order for the caller to store. Never call this inside a transaction.
    """
    notifications = list(notifications)
    if not settings.FIREBASE_PUSH_ENABLED:
        return [_skipped(notification) for notification in notifications]

    eligible = [
        notification for notification in notifications
        if notification.recipient.is_active and not notification.recipient.must_change_password
    ]
    devices_by_user = {}
    if eligible:
        for device in PushDevice.objects.filter(
            user_id__in={notification.recipient_id for notification in eligible},
            is_active=True,
        ).order_by("id"):
            devices_by_user.setdefault(device.user_id, []).append(device)

    attempts = {}
    for notification in eligible:
        delivered = list(notification.push_delivered_device_ids)
        attempts[notification.id] = _Attempt(
            notification=notification,
            delivered_device_ids=delivered,
            targets=[
                device
                for device in _unique_token_devices(devices_by_user.get(notification.recipient_id, []))
                if str(device.id) not in delivered
            ],
        )

    deliveries = [
        (attempt, device)
        for attempt in attempts.values()
        for device in attempt.targets
    ]
    if deliveries:
        _send_deliveries(deliveries)

    # Retry delays count from the end of this attempt.
    now = timezone.now()
    return [
        _result_for(attempts.get(notification.id), notification, now)
        for notification in notifications
    ]


def _send_deliveries(deliveries):
    try:
        app = get_firebase_app()
    except Exception as error:
        logger.error(
            "Firebase initialization failed count=%s error=%s",
            len(deliveries),
            type(error).__name__,
        )
        for attempt, _device in deliveries:
            attempt.transient_error = type(error).__name__
        return

    dead_device_ids = []
    chunk_size = settings.PUSH_SEND_CHUNK_SIZE
    for start in range(0, len(deliveries), chunk_size):
        chunk = deliveries[start:start + chunk_size]
        try:
            # Never called with an empty list: send_each would raise
            # UnknownError from a zero-worker thread pool.
            responses = messaging.send_each(
                [
                    build_notification_message(notification=attempt.notification, token=device.fcm_token)
                    for attempt, device in chunk
                ],
                app=app,
            ).responses
        except Exception as error:
            logger.error(
                "Firebase batch send failed count=%s error=%s",
                len(chunk),
                type(error).__name__,
            )
            for attempt, _device in chunk:
                attempt.transient_error = type(error).__name__
            continue

        for (attempt, device), response in zip(chunk, responses):
            if response.success:
                attempt.delivered_device_ids.append(str(device.id))
            else:
                error = response.exception or firebase_exceptions.UnknownError(
                    "Firebase response had no message id."
                )
                _record_device_failure(attempt, device, error, dead_device_ids)

    if dead_device_ids:
        try:
            PushDevice.objects.filter(pk__in=dead_device_ids, is_active=True).update(
                is_active=False,
                updated_at=timezone.now(),
            )
        except DatabaseError as error:
            # The next attempt meets the same error and tries again.
            logger.error(
                "Disabling dead push devices failed count=%s error=%s",
                len(dead_device_ids),
                type(error).__name__,
            )


def _record_device_failure(attempt, device, error, dead_device_ids):
    error_name = type(error).__name__
    log_args = (attempt.notification.id, device.id, error_name)
    if isinstance(error, PERMANENT_ERRORS):
        attempt.permanent_error = error_name
        if isinstance(error, DEAD_TOKEN_ERRORS):
            dead_device_ids.append(device.id)
            logger.warning(
                "Dead Firebase token disabled notification_id=%s device_id=%s error=%s",
                *log_args,
            )
        else:
            logger.warning(
                "Firebase rejected push notification_id=%s device_id=%s error=%s",
                *log_args,
            )
    elif isinstance(error, CONFIGURATION_ERRORS):
        attempt.transient_error = error_name
        logger.error(
            "Firebase credentials or project rejected push "
            "notification_id=%s device_id=%s error=%s",
            *log_args,
        )
    else:
        attempt.transient_error = error_name
        logger.warning(
            "Firebase push failed, will retry notification_id=%s device_id=%s error=%s",
            *log_args,
        )


def _skipped(notification):
    return PushAttemptResult(
        notification_id=notification.id,
        status=Notification.PushStatus.SKIPPED,
        attempts=notification.push_attempts,
        delivered_device_ids=list(notification.push_delivered_device_ids),
    )


def _result_for(attempt, notification, now):
    if attempt is None:
        # Recipient is inactive or must change their password.
        return _skipped(notification)

    delivered = attempt.delivered_device_ids
    if not attempt.targets:
        # Nothing left to send: every active device already has it, or
        # the recipient has no active device.
        if not delivered:
            return _skipped(notification)
        return PushAttemptResult(
            notification_id=notification.id,
            status=Notification.PushStatus.SENT,
            attempts=notification.push_attempts,
            delivered_device_ids=delivered,
            sent_at=now,
        )

    attempts = notification.push_attempts + 1
    if attempt.transient_error:
        if attempts >= settings.PUSH_MAX_ATTEMPTS:
            return PushAttemptResult(
                notification_id=notification.id,
                status=Notification.PushStatus.FAILED,
                attempts=attempts,
                delivered_device_ids=delivered,
                error=attempt.transient_error,
            )
        delay = PUSH_RETRY_DELAYS[min(attempts, len(PUSH_RETRY_DELAYS)) - 1]
        return PushAttemptResult(
            notification_id=notification.id,
            status=Notification.PushStatus.PENDING,
            attempts=attempts,
            delivered_device_ids=delivered,
            next_attempt_at=now + delay,
            error=attempt.transient_error,
        )
    if delivered:
        return PushAttemptResult(
            notification_id=notification.id,
            status=Notification.PushStatus.SENT,
            attempts=attempts,
            delivered_device_ids=delivered,
            sent_at=now,
        )
    return PushAttemptResult(
        notification_id=notification.id,
        status=Notification.PushStatus.FAILED,
        attempts=attempts,
        delivered_device_ids=delivered,
        error=attempt.permanent_error,
    )
