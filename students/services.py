from django.db import transaction
from rest_framework.exceptions import ValidationError

from academics.models import Section

from .models import Enrollment, StudentAuditLog
from audit_logs.models import AuditLog
from audit_logs.services import log_event


@transaction.atomic
def transfer_student_between_sections(
    *,
    enrollment: Enrollment,
    target_section: Section,
    actor,
) -> Enrollment:
    locked_enrollment = (
        Enrollment.objects
        .select_for_update()
        .select_related(
            "student",
            "academic_year",
            "section",
            "section__grade_level",
        )
        .get(pk=enrollment.pk)
    )

    current_section = locked_enrollment.section

    if current_section.pk == target_section.pk:
        raise ValidationError(
            {
                "code": "STUDENT_ALREADY_IN_SECTION",
                "detail": "تعذّر نقل الطالب، لأنه مسجّل بالفعل في الشعبة المحددة.",
                "section": "اختر شعبة مختلفة عن شعبة الطالب الحالية.",
            }
        )

    if (
        target_section.academic_year_id
        != locked_enrollment.academic_year_id
    ):
        raise ValidationError(
            {
                "code": "SECTION_ACADEMIC_YEAR_MISMATCH",
                "detail": "تعذّر نقل الطالب، لأن الشعبة المحددة لا تتبع السنة الدراسية الحالية.",
                "section": "اختر شعبة تابعة للسنة الدراسية نفسها.",
            }
        )

    if (
        target_section.grade_level_id
        != current_section.grade_level_id
    ):
        raise ValidationError(
            {
                "code": "SECTION_GRADE_MISMATCH",
                "detail": "تعذّر نقل الطالب، لأن الشعبة المحددة تتبع صفًا دراسيًا مختلفًا.",
                "section": "اختر شعبة تابعة للصف الدراسي الحالي للطالب.",
            }
        )

    old_section = current_section

    locked_enrollment.section = target_section
    locked_enrollment.save(
        update_fields=[
            "section",
            "updated_at",
        ]
    )

    StudentAuditLog.objects.create(
        event_type=StudentAuditLog.EventType.SECTION_TRANSFER,
        actor=actor,
        enrollment=locked_enrollment,
        old_section=old_section,
        new_section=target_section,
    )

    log_event(
        actor=actor,
        action=AuditLog.Action.TRANSFER,
        instance=locked_enrollment,
        changes={
            "section": {"before": old_section.pk, "after": target_section.pk}
        },
    )

    return locked_enrollment
