from django.db import transaction
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from .models import AppointmentRequest


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

    return locked_appointment
