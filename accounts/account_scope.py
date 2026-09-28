from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from academics.models import AcademicYear, SupervisorScope
from teaching.models import TeacherAssignment


def active_teacher_assignments(*, on_date=None):
    on_date = on_date or timezone.localdate()
    return TeacherAssignment.objects.filter(
        start_date__lte=on_date,
    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=on_date))


def teacher_accounts_visible_to_supervisor(queryset, supervisor, *, on_date=None):
    return queryset


def can_view_teacher_account(supervisor, teacher, *, on_date=None):
    return teacher_accounts_visible_to_supervisor(
        type(teacher).objects.filter(pk=teacher.pk),
        supervisor,
        on_date=on_date,
    ).exists()


can_edit_teacher_account = can_view_teacher_account
can_reset_teacher_password = can_view_teacher_account


def guardian_accounts_visible_to_supervisor(queryset, supervisor):
    from students.models import GuardianStudent

    scope = SupervisorScope.objects.filter(supervisor=supervisor).first()
    if scope is None:
        return queryset.none()

    active_year = AcademicYear.objects.filter(
        status=AcademicYear.Status.ACTIVE,
    ).first()
    if active_year is None:
        return queryset.none()

    visible_links = GuardianStudent.objects.filter(
        guardian_id=OuterRef("pk"),
        is_active=True,
        student__enrollments__academic_year=active_year,
    )
    if scope.scope_type != SupervisorScope.ScopeType.ALL:
        visible_links = visible_links.filter(
            student__enrollments__section__grade_level__stage__in=(
                scope.stages.values_list("stage", flat=True)
            ),
        )

    return queryset.annotate(
        _supervisor_has_visible_student=Exists(visible_links),
    ).filter(_supervisor_has_visible_student=True)


def can_view_guardian_account(supervisor, guardian):
    return guardian_accounts_visible_to_supervisor(
        type(guardian).objects.filter(pk=guardian.pk),
        supervisor,
    ).exists()


def can_use_guardian_for_student_link(supervisor, guardian):
    if can_view_guardian_account(supervisor, guardian):
        return True
    return bool(
        guardian.created_by_id == supervisor.pk
        and not guardian.guardian_student_links.exists()
    )


def can_set_teacher_active(supervisor, teacher, *, on_date=None):
    return True
