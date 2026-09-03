from django.contrib.auth import get_user_model
from django.utils import timezone

from academics.models import AcademicYear
from students.models import Enrollment

from notifications.models import Notification
from notifications.services import create_notification

from .models import Announcement


User = get_user_model()


def notify_announcement_published(announcement):
    today = timezone.localdate()
    if announcement.publish_date > today:
        return []
    if announcement.expiry_date and announcement.expiry_date < today:
        return []

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

    notifications = []
    for guardian in guardians:
        notification, _created = create_notification(
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
        )
        notifications.append(notification)
    return notifications
