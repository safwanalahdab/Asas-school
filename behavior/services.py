from students.models import GuardianStudent

from notifications.models import Notification
from notifications.services import create_notification


def notify_behavior_note_created(behavior_note):
    student = behavior_note.enrollment.student
    link = GuardianStudent.objects.select_related("guardian").filter(
        student=student,
        student__is_active=True,
        is_active=True,
        guardian__is_active=True,
        guardian__role="guardian",
    ).first()
    if link is None:
        return None

    notification, _created = create_notification(
        recipient=link.guardian,
        notification_type=Notification.NotificationType.BEHAVIOR,
        title="ملاحظة سلوكية جديدة",
        body=(
            "تمت إضافة ملاحظة سلوكية جديدة للطالب. "
            "يمكنك مراجعة التفاصيل داخل التطبيق."
        ),
        student=student,
        resource_type="behavior",
        resource_id=behavior_note.id,
        event_key=f"behavior:{behavior_note.id}:created",
    )
    return notification


def notify_student_point_entry_created(point_entry):
    student = point_entry.enrollment.student
    guardian_links = GuardianStudent.objects.select_related("guardian").filter(
        student=student,
        student__is_active=True,
        is_active=True,
        guardian__is_active=True,
        guardian__role="guardian",
    )

    notifications = []
    for link in guardian_links:
        notification, _created = create_notification(
            recipient=link.guardian,
            notification_type=Notification.NotificationType.BEHAVIOR,
            title="تمت إضافة نقاط جديدة",
            body=(
                f"تمت إضافة {point_entry.points} نقاط "
                f"للطالب {student.full_name}."
            ),
            student=student,
            resource_type="student_points",
            resource_id=point_entry.id,
            event_key=f"student_points:{point_entry.id}:created",
        )
        notifications.append(notification)
    return notifications
