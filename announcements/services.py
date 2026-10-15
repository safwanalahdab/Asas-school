import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from academics.models import AcademicYear
from students.models import Enrollment

from notifications.models import Notification
from notifications.services import create_notifications

from .models import Announcement


User = get_user_model()
logger = logging.getLogger(__name__)

DUE_BATCH_SIZE = 100


def notify_announcement_published(announcement):
    """Create the publish notifications once the publish date has arrived.

    Marks the announcement as handled (publish_notified_at) even when it has
    already expired, so the scheduled job does not check it again.
    """
    today = timezone.localdate()
    if announcement.publish_date > today:
        return []

    with transaction.atomic():
        notifications = []
        if not (announcement.expiry_date and announcement.expiry_date < today):
            notifications = _create_publish_notifications(announcement)
        # A queryset update keeps updated_at and the other fields untouched.
        notified_at = timezone.now()
        Announcement.objects.filter(pk=announcement.pk).update(
            publish_notified_at=notified_at,
        )
        announcement.publish_notified_at = notified_at
    return notifications


def _create_publish_notifications(announcement):
    enrollments = Enrollment.objects.filter(
        academic_year__status=AcademicYear.Status.ACTIVE,
        student__is_active=True,
        student__guardian_link__is_active=True,
        student__guardian_link__guardian__is_active=True,
        student__guardian_link__guardian__role=User.Role.GUARDIAN,
    )
    if announcement.scope == Announcement.Scope.GRADES:
        enrollments = enrollments.filter(
            section__grade_level__in=announcement.grade_levels.all()
        )
    elif announcement.scope == Announcement.Scope.SECTIONS:
        enrollments = enrollments.filter(section__in=announcement.sections.all())

    guardian_ids = enrollments.values_list(
        "student__guardian_link__guardian_id", flat=True
    ).distinct()
    guardians = User.objects.filter(pk__in=guardian_ids, is_active=True)

    specs = []
    for guardian in guardians:
        specs.append(dict(
            recipient=guardian,
            notification_type=Notification.NotificationType.ANNOUNCEMENT,
            title="إعلان جديد",
            body=(
                "تم نشر إعلان جديد من المدرسة. "
                "يمكنك مراجعة التفاصيل داخل التطبيق."
            ),
            student=None,
            resource_type="announcement",
            resource_id=announcement.id,
            event_key=f"announcement:{announcement.id}:published",
        ))
    return [notification for notification, _created in create_notifications(specs)]


def notify_due_announcements(*, now=None, batch_size=DUE_BATCH_SIZE):
    """Notify announcements whose publish date has arrived but were not yet.

    Does nothing before ANNOUNCEMENT_NOTIFY_HOUR local time, so guardians are
    not notified at midnight. Returns the number of announcements handled.
    """
    local_now = timezone.localtime(now)
    if local_now.hour < settings.ANNOUNCEMENT_NOTIFY_HOUR:
        return 0

    due = Announcement.objects.filter(
        publish_notified_at__isnull=True,
        publish_date__lte=local_now.date(),
    ).order_by("publish_date", "pk")
    processed = failed = 0
    after = None
    while True:
        batch = due
        if after is not None:
            # Keyset paging: failed or locked rows stay NULL and are not
            # fetched again in this run.
            batch = batch.filter(
                Q(publish_date__gt=after[0])
                | Q(publish_date=after[0], pk__gt=after[1])
            )
        rows = list(batch.values_list("publish_date", "pk")[:batch_size])
        if not rows:
            break
        for _publish_date, announcement_id in rows:
            try:
                if _notify_due_announcement(announcement_id, local_now.date()):
                    processed += 1
            except Exception as error:
                failed += 1
                logger.error(
                    "Scheduled announcement notification failed "
                    "announcement_id=%s error=%s",
                    announcement_id,
                    type(error).__name__,
                )
        after = rows[-1]

    if processed or failed:
        logger.info(
            "Scheduled announcement notifications processed=%s failed=%s",
            processed,
            failed,
        )
    return processed


def _notify_due_announcement(announcement_id, today):
    with transaction.atomic():
        # Under READ COMMITTED the filter is re-checked on the locked row, so
        # an announcement another process has just handled is not returned.
        announcement = (
            Announcement.objects.select_for_update(skip_locked=True, of=("self",))
            .filter(
                pk=announcement_id,
                publish_notified_at__isnull=True,
                publish_date__lte=today,
            )
            .first()
        )
        if announcement is None:
            return False
        notify_announcement_published(announcement)
        return announcement.publish_notified_at is not None
