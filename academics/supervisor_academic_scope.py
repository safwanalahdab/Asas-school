from dataclasses import dataclass

from django.db.models import Exists, OuterRef, Q

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
        # .all() reuses the prefetched rows; values_list() would query again.
        stages=frozenset(item.stage for item in scope.stages.all()),
    )


def is_stage_scoped_supervisor(user):
    return supervisor_academic_scope_for(user).applies


def scope_allows_stage(scope, stage):
    """Decide a stage against an already-loaded scope, avoiding a reload."""
    if not scope.applies or scope.allows_all_stages:
        return True
    return bool(scope.scope_type and stage in scope.stages)


def is_stage_allowed(user, stage):
    return scope_allows_stage(supervisor_academic_scope_for(user), stage)


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
    """Scope active-year placements while keeping current-year unassigned visible."""
    scope = supervisor_academic_scope_for(user)
    if not scope.applies or scope.allows_all_stages:
        return queryset

    active_year = get_active_academic_year()
    if active_year is None:
        return queryset.none()

    # Imported lazily so the academics policy does not create a model import cycle.
    from students.models import Enrollment

    active_enrollment = Enrollment.objects.filter(
        student_id=OuterRef("pk"),
        academic_year=active_year,
    )
    matching_enrollment = Enrollment.objects.filter(
        student_id=OuterRef("pk"),
        academic_year=active_year,
        section__grade_level__stage__in=scope.stages,
    )
    return queryset.annotate(
        _supervisor_has_active_enrollment=Exists(active_enrollment),
        _supervisor_has_active_stage_enrollment=Exists(matching_enrollment)
    ).filter(
        Q(_supervisor_has_active_stage_enrollment=True)
        | Q(_supervisor_has_active_enrollment=False)
    )


def can_access_grade_level(user, grade_level):
    return is_stage_allowed(user, grade_level.stage)


# Resolve the scope before touching FK relations so unscoped users never
# trigger lazy section/grade-level loads.
def can_access_section(user, section):
    scope = supervisor_academic_scope_for(user)
    if not scope.applies or scope.allows_all_stages:
        return True
    return scope_allows_stage(scope, section.grade_level.stage)


def can_access_enrollment(user, enrollment):
    scope = supervisor_academic_scope_for(user)
    if not scope.applies or scope.allows_all_stages:
        return True
    return scope_allows_stage(scope, enrollment.section.grade_level.stage)


def can_access_student(user, student):
    return filter_students_by_supervisor_scope(
        type(student).objects.filter(pk=student.pk), user
    ).exists()


def can_create_enrollment_for_student(user, student):
    """Allow unplaced students, but reject active-year placements outside scope."""
    scope = supervisor_academic_scope_for(user)
    if not scope.applies or scope.allows_all_stages:
        return True
    if not scope.scope_type:
        return False

    active_year = get_active_academic_year()
    if active_year is None:
        return True

    # Imported lazily so the academics policy does not create a model import cycle.
    from students.models import Enrollment

    return not Enrollment.objects.filter(
        student=student,
        academic_year=active_year,
    ).exclude(
        section__grade_level__stage__in=scope.stages,
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
