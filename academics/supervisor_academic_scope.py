from dataclasses import dataclass

from django.db.models import Exists, OuterRef

from academics.models import AcademicYear, SupervisorScope


@dataclass(frozen=True)
class SupervisorAcademicScope:
    applies: bool
    scope_type: str | None = None
    stages: frozenset[str] = frozenset()

    @property
    def allows_all_stages(self):
        return self.applies and self.scope_type == SupervisorScope.ScopeType.ALL


def supervisor_academic_scope_for(user):
    """Return the stage-scope state without changing non-supervisor behavior."""
    if (
        user is None
        or getattr(user, "is_superuser", False)
        or getattr(user, "role", None) != "supervisor"
    ):
        return SupervisorAcademicScope(applies=False)

    scope = (
        SupervisorScope.objects.filter(supervisor=user)
        .prefetch_related("stages")
        .first()
    )
    if scope is None:
        return SupervisorAcademicScope(applies=True)

    return SupervisorAcademicScope(
        applies=True,
        scope_type=scope.scope_type,
        stages=frozenset(scope.stages.values_list("stage", flat=True)),
    )


def is_stage_scoped_supervisor(user):
    return supervisor_academic_scope_for(user).applies


def is_stage_allowed(user, stage):
    scope = supervisor_academic_scope_for(user)
    if not scope.applies or scope.allows_all_stages:
        return True
    return bool(scope.scope_type and stage in scope.stages)


def filter_queryset_by_stage(queryset, user, *, stage_lookup="stage"):
    """Filter a queryset whose stage is direct or reachable by a lookup path."""
    scope = supervisor_academic_scope_for(user)
    if not scope.applies or scope.allows_all_stages:
        return queryset
    if not scope.scope_type:
        return queryset.none()
    return queryset.filter(**{f"{stage_lookup}__in": scope.stages})


def filter_enrollments_by_supervisor_scope(queryset, user):
    """Enrollment scope is historical and always follows its own section."""
    return filter_queryset_by_stage(
        queryset,
        user,
        stage_lookup="section__grade_level__stage",
    )


def get_active_academic_year():
    return AcademicYear.objects.filter(status=AcademicYear.Status.ACTIVE).first()


def filter_students_by_supervisor_scope(queryset, user):
    """Student scope follows only the enrollment in the active academic year."""
    scope = supervisor_academic_scope_for(user)
    if not scope.applies or scope.allows_all_stages:
        return queryset
    if not scope.scope_type:
        return queryset.none()

    active_year = get_active_academic_year()
    if active_year is None:
        return queryset.none()

    # Imported lazily so the academics policy does not create a model import cycle.
    from students.models import Enrollment

    matching_enrollment = Enrollment.objects.filter(
        student_id=OuterRef("pk"),
        academic_year=active_year,
        section__grade_level__stage__in=scope.stages,
    )
    return queryset.annotate(
        _supervisor_has_active_stage_enrollment=Exists(matching_enrollment)
    ).filter(_supervisor_has_active_stage_enrollment=True)


def can_access_grade_level(user, grade_level):
    return is_stage_allowed(user, grade_level.stage)


def can_access_section(user, section):
    return is_stage_allowed(user, section.grade_level.stage)


def can_access_enrollment(user, enrollment):
    return can_access_section(user, enrollment.section)


def can_access_student(user, student):
    return filter_students_by_supervisor_scope(
        type(student).objects.filter(pk=student.pk), user
    ).exists()


def can_manage_global_academic_resources(user):
    """Selected/missing supervisor scopes cannot mutate school-wide resources."""
    scope = supervisor_academic_scope_for(user)
    return not scope.applies or scope.allows_all_stages


def can_change_grade_level_stage(user, grade_level, new_stage):
    """A selected-stage supervisor may not move a grade level between stages."""
    scope = supervisor_academic_scope_for(user)
    if not scope.applies or scope.allows_all_stages:
        return True
    if not scope.scope_type:
        return False
    return grade_level.stage == new_stage and new_stage in scope.stages
