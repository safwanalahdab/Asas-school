from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from academics.models import SupervisorScope
from teaching.models import TeacherAssignment


def active_teacher_assignments(*, on_date=None):
    on_date = on_date or timezone.localdate()
    return TeacherAssignment.objects.filter(
        start_date__lte=on_date,
    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=on_date))


def teacher_accounts_visible_to_supervisor(queryset, supervisor, *, on_date=None):
    scope = SupervisorScope.objects.filter(supervisor=supervisor).first()
    if scope is None:
        return queryset.none()
    if scope.scope_type == SupervisorScope.ScopeType.ALL:
        return queryset

    active = active_teacher_assignments(on_date=on_date).filter(
        teacher_id=OuterRef("pk"),
    )
    stages = scope.stages.values_list("stage", flat=True)
    matching = active.filter(
        section__grade_level__stage__in=stages,
    )

    return queryset.annotate(
        _supervisor_has_active_assignment=Exists(active),
        _supervisor_has_matching_assignment=Exists(matching),
    ).filter(
        Q(_supervisor_has_matching_assignment=True)
        | Q(
            _supervisor_has_active_assignment=False,
            created_by=supervisor,
        )
    )


def can_view_teacher_account(supervisor, teacher, *, on_date=None):
    return teacher_accounts_visible_to_supervisor(
        type(teacher).objects.filter(pk=teacher.pk),
        supervisor,
        on_date=on_date,
    ).exists()


can_edit_teacher_account = can_view_teacher_account
can_reset_teacher_password = can_view_teacher_account


def can_set_teacher_active(supervisor, teacher, *, on_date=None):
    scope = SupervisorScope.objects.filter(supervisor=supervisor).first()
    if scope is None:
        return False
    if scope.scope_type == SupervisorScope.ScopeType.ALL:
        return True

    allowed_stages = scope.stages.values_list("stage", flat=True)
    active = active_teacher_assignments(on_date=on_date).filter(teacher=teacher)
    if not active.exists():
        return False
    return not active.exclude(
        section__grade_level__stage__in=allowed_stages
    ).exists()
