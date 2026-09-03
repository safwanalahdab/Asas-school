from students.models import GuardianStudent

from notifications.models import Notification
from notifications.services import create_notification


def notify_school_request_answered(school_request):
    guardian = school_request.guardian
    student = school_request.student
    if not guardian.is_active:
        return None
    if student is not None and not GuardianStudent.objects.filter(
        guardian=guardian,
        student=student,
        is_active=True,
        student__is_active=True,
    ).exists():
        return None

    notification, _created = create_notification(
        recipient=guardian,
        notification_type=Notification.NotificationType.SCHOOL_REQUEST,
        title="تم الرد على طلبك",
        body=(
            "تم الرد على طلبك المرسل إلى المدرسة. "
            "يمكنك مراجعة التفاصيل داخل التطبيق."
        ),
        student=student,
        resource_type="school_request",
        resource_id=school_request.id,
        event_key=f"school_request:{school_request.id}:answered",
    )
    return notification
