"""Push outbox worker: claims pending notifications and sends them.

The HTTP request only stores a pending Notification row. This worker runs
as its own process (``manage.py run_push_worker``) and never holds a
database lock while talking to Firebase.
"""

import logging
import threading
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import Count, Min, Q
from django.utils import timezone

from .models import Notification
from .push_services import send_claimed_notifications


logger = logging.getLogger(__name__)

PENDING = Notification.PushStatus.PENDING
# Expired rows are marked in bounded chunks so one claim stays short.
EXPIRE_CHUNK_SIZE = 1000
MAX_ERROR_BACKOFF_SECONDS = 60

_RESULT_COUNTERS = {
    Notification.PushStatus.SENT: "sent",
    Notification.PushStatus.PENDING: "retry",
    Notification.PushStatus.FAILED: "failed",
    Notification.PushStatus.SKIPPED: "skipped",
}


@dataclass(frozen=True)
class ClaimedBatch:
    lease_token: uuid.UUID
    notifications: list
    expired: int


@dataclass(frozen=True)
class BatchSummary:
    claimed: int = 0
    sent: int = 0
    retry: int = 0
    failed: int = 0
    skipped: int = 0
    expired: int = 0
    lease_lost: int = 0

    @property
    def busy(self):
        """More work is probably waiting, so the worker should not sleep."""
        return (
            self.claimed >= settings.PUSH_WORKER_BATCH_SIZE
            or self.expired >= EXPIRE_CHUNK_SIZE
        )


@dataclass(frozen=True)
class QueueStatus:
    counts: dict
    oldest_pending_age_seconds: float | None
    oldest_due_overdue_seconds: float | None


def _lease_free(now):
    return Q(push_locked_until__isnull=True) | Q(push_locked_until__lt=now)


def claim_batch():
    """Expire stale rows and lease up to PUSH_WORKER_BATCH_SIZE due rows."""
    now = timezone.now()
    lease_token = uuid.uuid4()
    with transaction.atomic():
        expired_ids = list(
            Notification.objects.select_for_update(skip_locked=True)
            .filter(
                _lease_free(now),
                push_status=PENDING,
                created_at__lt=now - timedelta(hours=settings.PUSH_MAX_AGE_HOURS),
            )
            .order_by("created_at")
            .values_list("pk", flat=True)[:EXPIRE_CHUNK_SIZE]
        )
        if expired_ids:
            Notification.objects.filter(pk__in=expired_ids).update(
                push_status=Notification.PushStatus.EXPIRED,
                push_next_attempt_at=None,
                push_lease_token=None,
                push_locked_until=None,
                updated_at=now,
            )

        notifications = list(
            Notification.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("recipient")
            .filter(
                _lease_free(now),
                push_status=PENDING,
                push_next_attempt_at__lte=now,
            )
            .order_by("created_at")[:settings.PUSH_WORKER_BATCH_SIZE]
        )
        if notifications:
            locked_until = now + timedelta(seconds=settings.PUSH_LEASE_SECONDS)
            Notification.objects.filter(
                pk__in=[notification.pk for notification in notifications]
            ).update(
                push_lease_token=lease_token,
                push_locked_until=locked_until,
                updated_at=now,
            )
            for notification in notifications:
                notification.push_lease_token = lease_token
                notification.push_locked_until = locked_until
    return ClaimedBatch(
        lease_token=lease_token,
        notifications=notifications,
        expired=len(expired_ids),
    )


def record_results(results, *, lease_token):
    """Store attempt results for rows this worker still holds the lease on.

    A row whose lease was taken over by another worker is left untouched.
    """
    now = timezone.now()
    counts = Counter()
    with transaction.atomic():
        for result in results:
            updated = Notification.objects.filter(
                pk=result.notification_id,
                push_status=PENDING,
                push_lease_token=lease_token,
            ).update(
                push_status=result.status,
                push_attempts=result.attempts,
                push_next_attempt_at=result.next_attempt_at,
                push_sent_at=result.sent_at,
                push_last_error=result.error[:100],
                push_delivered_device_ids=result.delivered_device_ids,
                push_lease_token=None,
                push_locked_until=None,
                updated_at=now,
            )
            if updated:
                counts[_RESULT_COUNTERS[result.status]] += 1
            else:
                counts["lease_lost"] += 1
                logger.warning(
                    "Push lease lost, result discarded notification_id=%s",
                    result.notification_id,
                )
    return counts


def process_batch():
    """Claim, send outside any transaction, then record one batch."""
    batch = claim_batch()
    counts = Counter()
    if batch.notifications:
        results = send_claimed_notifications(batch.notifications)
        counts = record_results(results, lease_token=batch.lease_token)

    summary = BatchSummary(
        claimed=len(batch.notifications),
        expired=batch.expired,
        **counts,
    )
    if summary.claimed or summary.expired:
        logger.info(
            "Push batch claimed=%s sent=%s retry=%s failed=%s skipped=%s "
            "expired=%s lease_lost=%s",
            summary.claimed,
            summary.sent,
            summary.retry,
            summary.failed,
            summary.skipped,
            summary.expired,
            summary.lease_lost,
        )
    return summary


class PushWorker:
    """Runs process_batch until stop() is called (from a signal handler)."""

    def __init__(self):
        self._stop = threading.Event()

    def stop(self, *_signal_args):
        self._stop.set()

    def run(self):
        logger.info("Push worker started")
        failures = 0
        while not self._stop.is_set():
            try:
                close_old_connections()
                summary = process_batch()
            except Exception as error:
                failures += 1
                delay = min(
                    MAX_ERROR_BACKOFF_SECONDS,
                    settings.PUSH_WORKER_POLL_SECONDS * 2 ** min(failures - 1, 6),
                )
                logger.error(
                    "Push worker batch failed error=%s retry_in_seconds=%s",
                    type(error).__name__,
                    delay,
                )
                self._stop.wait(delay)
                continue

            failures = 0
            if not summary.busy:
                self._stop.wait(settings.PUSH_WORKER_POLL_SECONDS)
        logger.info("Push worker stopped")


def get_queue_status():
    now = timezone.now()
    counts = {status: 0 for status in Notification.PushStatus.values}
    counts.update(
        Notification.objects.order_by()
        .values_list("push_status")
        .annotate(total=Count("pk"))
    )
    pending = Notification.objects.filter(push_status=PENDING)
    oldest_created = pending.aggregate(value=Min("created_at"))["value"]
    oldest_due = pending.filter(push_next_attempt_at__lte=now).aggregate(
        value=Min("push_next_attempt_at")
    )["value"]
    return QueueStatus(
        counts=counts,
        oldest_pending_age_seconds=(
            (now - oldest_created).total_seconds() if oldest_created else None
        ),
        oldest_due_overdue_seconds=(
            (now - oldest_due).total_seconds() if oldest_due else None
        ),
    )
