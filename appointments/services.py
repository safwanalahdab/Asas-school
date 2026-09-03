from django.db import transaction
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from notifications.models import Notification
from notifications.services import create_notification

from .models import AppointmentRequest


APPOINTMENT_NOTIFICATION_TITLE = "\u062a\u0645 \u062a\u062d\u062f\u064a\u062b \u0637\u0644\u0628 \u0627\u0644\u0645\u0648\u0639\u062f"
APPOINTMENT_APPROVED_BODY = "\u062a\u0645\u062a \u0627\u0644\u0645\u0648\u0627\u0641\u0642\u0629 \u0639\u0644\u0649 \u0637\u0644\u0628 \u0627\u0644\u0645\u0648\u0639\u062f \u0627\u0644\u062e\u0627\u0635 \u0628\u0643."
APPOINTMENT_REJECTED_BODY = (
    "\u062a\u0645 \u0631\u0641\u0636 \u0637\u0644\u0628 \u0627\u0644\u0645\u0648\u0639\u062f \u0627\u0644\u062e\u0627\u0635 \u0628\u0643. "
    "\u064a\u0645\u0643\u0646\u0643 \u0645\u0631\u0627\u062c\u0639\u0629 \u062a\u0641\u0627\u0635\u064a\u0644 \u0627\u0644\u0637\u0644\u0628 \u0644\u0645\u0639\u0631\u0641\u0629 \u0627\u0644\u0633\u0628\u0628."
)


def _validate_decision_reason(decision_reason):
    decision_reason = decision_reason.strip()

    if not decision_reason:
        raise ValidationError(
            {
                "decision_reason": (
                    "يجب إدخال سبب القرار."
                )
            }
        )

    return decision_reason


@transaction.atomic
def approve_appointment_request(
    *,
    appointment,
    actor,
):
    locked_appointment = (
        AppointmentRequest.objects
        .select_for_update()
        .get(
            pk=appointment.pk,
        )
    )

    if (
        locked_appointment.status
        != AppointmentRequest.Status.PENDING
    ):
        raise ValidationError(
            {
                "status": (
                    "تم اتخاذ قرار بشأن هذا الطلب مسبقًا."
                )
            }
        )

    decision_time = timezone.now()

    locked_appointment.status = (
        AppointmentRequest.Status.APPROVED
    )
    locked_appointment.decision_reason = ""
    locked_appointment.decided_by = actor
    locked_appointment.decided_at = decision_time

    locked_appointment.save(
        update_fields=[
            "status",
            "decision_reason",
            "decided_by",
            "decided_at",
            "updated_at",
        ]
    )

    create_notification(
        recipient=locked_appointment.guardian,
        notification_type=Notification.NotificationType.APPOINTMENT,
        title=APPOINTMENT_NOTIFICATION_TITLE,
        body=APPOINTMENT_APPROVED_BODY,
        student=None,
        resource_type="appointment",
        resource_id=locked_appointment.id,
        event_key=f"appointment:{locked_appointment.id}:approved",
    )

    return locked_appointment


@transaction.atomic
def reject_appointment_request(
    *,
    appointment,
    actor,
    decision_reason,
):
    decision_reason = _validate_decision_reason(
        decision_reason
    )

    locked_appointment = (
        AppointmentRequest.objects
        .select_for_update()
        .get(
            pk=appointment.pk,
        )
    )

    if (
        locked_appointment.status
        != AppointmentRequest.Status.PENDING
    ):
        raise ValidationError(
            {
                "status": (
                    "تم اتخاذ قرار بشأن هذا الطلب مسبقًا."
                )
            }
        )

    decision_time = timezone.now()

    locked_appointment.status = (
        AppointmentRequest.Status.REJECTED
    )
    locked_appointment.decision_reason = (
        decision_reason
    )
    locked_appointment.decided_by = actor
    locked_appointment.decided_at = decision_time

    locked_appointment.save(
        update_fields=[
            "status",
            "decision_reason",
            "decided_by",
            "decided_at",
            "updated_at",
        ]
    )

    create_notification(
        recipient=locked_appointment.guardian,
        notification_type=Notification.NotificationType.APPOINTMENT,
        title=APPOINTMENT_NOTIFICATION_TITLE,
        body=APPOINTMENT_REJECTED_BODY,
        student=None,
        resource_type="appointment",
        resource_id=locked_appointment.id,
        event_key=f"appointment:{locked_appointment.id}:rejected",
    )

    return locked_appointment
