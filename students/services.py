from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from accounts.models import User
from accounts.services import assign_temporary_password
from academics.models import Section

from .models import (
    Enrollment,
    GuardianStudent,
    Student,
    StudentAuditLog,
    StudentHealthProfile,
)
from audit_logs.models import AuditLog
from audit_logs.services import get_actor_display, record_audit_event


def ensure_student_health_profile(student):
    health_profile, _ = StudentHealthProfile.objects.get_or_create(
        student=student,
    )
    return health_profile


@transaction.atomic
def register_student(
    *,
    student_data,
    health_profile_data=None,
    guardian_data=None,
):
    student = Student.objects.create(**student_data)
    health_profile = ensure_student_health_profile(student)

    if health_profile_data:
        health_fields = list(health_profile_data)
        for field_name, value in health_profile_data.items():
            setattr(health_profile, field_name, value)
        health_profile.save(update_fields=[*health_fields, "updated_at"])

    guardian_account = {
        "status": "not_created",
        "username": None,
        "temporary_password": None,
    }

    if guardian_data:
        national_id = guardian_data["national_id"]
        guardian = User.objects.filter(national_id=national_id).first()

        if guardian is not None and guardian.role != User.Role.GUARDIAN:
            raise ValidationError(
                {
                    "guardian": {
                        "national_id": (
                            "الرقم الوطني مرتبط بحساب لا يخص ولي أمر."
                        ),
                    },
                }
            )

        if guardian is None:
            if User.objects.filter(username=national_id).exists():
                raise ValidationError(
                    {
                        "guardian": {
                            "national_id": (
                                "الرقم الوطني مستخدم كاسم مستخدم لحساب آخر."
                            ),
                        },
                    }
                )

            guardian = User(
                username=national_id,
                national_id=national_id,
                phone_number=guardian_data.get("phone_number", ""),
                role=User.Role.GUARDIAN,
                first_name=guardian_data["first_name"],
                last_name=guardian_data["last_name"],
            )
            temporary_password = assign_temporary_password(guardian)
            try:
                with transaction.atomic():
                    guardian.save()
            except IntegrityError:
                guardian = User.objects.filter(national_id=national_id).first()
                if guardian is None or guardian.role != User.Role.GUARDIAN:
                    raise ValidationError(
                        {
                            "guardian": {
                                "national_id": (
                                    "تعذر إنشاء حساب ولي الأمر لأن الرقم الوطني "
                                    "أو اسم المستخدم مستخدم مسبقًا."
                                ),
                            },
                        }
                    )
                temporary_password = None
                guardian_status = "linked_existing"
            else:
                guardian_status = "created"
        else:
            temporary_password = None
            guardian_status = "linked_existing"

        GuardianStudent.objects.create(
            guardian=guardian,
            student=student,
            relationship=guardian_data["relationship"],
        )
        guardian_account = {
            "status": guardian_status,
            "username": guardian.username,
            "temporary_password": temporary_password,
        }

    return {
        "student": student,
        "guardian_account": guardian_account,
    }


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

    actor_name = get_actor_display(actor)
    record_audit_event(
        actor=actor, module=AuditLog.Module.STUDENTS,
        action=AuditLog.Action.TRANSFER,
        message=f"نقل {actor_name} الطالب {locked_enrollment.student.full_name} من الشعبة {old_section} إلى الشعبة {target_section}.",
        target=locked_enrollment,
        metadata={"old_section": str(old_section), "new_section": str(target_section)},
    )

    return locked_enrollment


@transaction.atomic
def correct_enrollment_placement(
    *,
    enrollment: Enrollment,
    target_section: Section,
    reason: str,
    actor,
) -> Enrollment:
    from attendance.models import AttendanceRecord
    from grades.models import StudentScore

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
    locked_target_section = (
        Section.objects
        .select_related("academic_year", "grade_level")
        .get(pk=target_section.pk)
    )
    current_section = locked_enrollment.section
    normalized_reason = reason.strip()

    if not normalized_reason:
        raise ValidationError(
            {
                "code": "PLACEMENT_CORRECTION_REASON_REQUIRED",
                "detail": "سبب تصحيح الشعبة مطلوب.",
                "reason": "سبب التصحيح لا يمكن أن يكون فارغًا.",
            }
        )

    if current_section.pk == locked_target_section.pk:
        raise ValidationError(
            {
                "code": "STUDENT_ALREADY_IN_SECTION",
                "detail": "الطالب مسجّل بالفعل في الشعبة المحددة.",
                "section": "اختر شعبة مختلفة عن شعبة الطالب الحالية.",
            }
        )

    if locked_target_section.academic_year_id != locked_enrollment.academic_year_id:
        raise ValidationError(
            {
                "code": "SECTION_ACADEMIC_YEAR_MISMATCH",
                "detail": "لا يمكن تصحيح التسجيل إلى شعبة من سنة دراسية مختلفة.",
                "section": "اختر شعبة تابعة للسنة الدراسية نفسها.",
            }
        )

    if locked_target_section.grade_level_id != current_section.grade_level_id:
        raise ValidationError(
            {
                "code": "SECTION_GRADE_MISMATCH",
                "detail": "لا يمكن تصحيح التسجيل إلى صف دراسي مختلف.",
                "section": "اختر شعبة تابعة للصف الدراسي نفسه.",
            }
        )

    if AttendanceRecord.objects.filter(enrollment=locked_enrollment).exists():
        raise ValidationError(
            {
                "code": "PLACEMENT_CORRECTION_BLOCKED_BY_ATTENDANCE",
                "detail": "لا يمكن تصحيح الشعبة لوجود سجلات حضور مرتبطة بالتسجيل.",
            }
        )

    if StudentScore.objects.filter(enrollment=locked_enrollment).exists():
        raise ValidationError(
            {
                "code": "PLACEMENT_CORRECTION_BLOCKED_BY_GRADES",
                "detail": "لا يمكن تصحيح الشعبة لوجود علامات مرتبطة بالتسجيل.",
            }
        )

    if StudentAuditLog.objects.filter(
        enrollment=locked_enrollment,
        event_type=StudentAuditLog.EventType.SECTION_TRANSFER,
    ).exists():
        raise ValidationError(
            {
                "code": "PLACEMENT_CORRECTION_BLOCKED_BY_TRANSFER",
                "detail": "لا يمكن تصحيح الشعبة لوجود سجل نقل سابق لهذا التسجيل.",
            }
        )

    locked_enrollment.section = locked_target_section
    locked_enrollment.save(update_fields=["section", "updated_at"])

    StudentAuditLog.objects.create(
        event_type=StudentAuditLog.EventType.PLACEMENT_CORRECTION,
        actor=actor,
        enrollment=locked_enrollment,
        old_section=current_section,
        new_section=locked_target_section,
        reason=normalized_reason,
    )

    return locked_enrollment
