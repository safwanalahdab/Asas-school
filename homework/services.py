from academics.models import AcademicYear
from students.models import Enrollment

from notifications.models import Notification
from notifications.services import create_notification


def notify_homework_created(homework):
    assignment = homework.teacher_assignment
    enrollments = Enrollment.objects.filter(
        section=assignment.section,
        academic_year=assignment.grade_subject.academic_year,
        academic_year__status=AcademicYear.Status.ACTIVE,
        student__is_active=True,
        student__guardian_link__is_active=True,
        student__guardian_link__guardian__is_active=True,
        student__guardian_link__guardian__role="guardian",
    ).select_related("student", "student__guardian_link__guardian")

    notifications = []
    for enrollment in enrollments:
        student = enrollment.student
        guardian = student.guardian_link.guardian
        notification, _created = create_notification(
            recipient=guardian,
            notification_type=Notification.NotificationType.HOMEWORK,
            title="واجب جديد",
            body=(
                "تمت إضافة واجب جديد للطالب. "
                "يمكنك مراجعة التفاصيل داخل التطبيق."
            ),
            student=student,
            resource_type="homework",
            resource_id=homework.id,
            event_key=f"homework:{homework.id}:student:{student.id}",
        )
        notifications.append(notification)
    return notifications
