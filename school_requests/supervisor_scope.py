from django.db.models import Exists, OuterRef

from academics.supervisor_academic_scope import (
    get_active_academic_year,
    supervisor_academic_scope_for,
)
from students.models import Enrollment


def filter_school_requests_by_supervisor_scope(queryset, user):
    scope = supervisor_academic_scope_for(user)
    if not scope.applies:
        return queryset
    if not scope.scope_type:
        return queryset.none()

    active_year = get_active_academic_year()
    if active_year is None:
        return queryset.none()

    active_enrollments = Enrollment.objects.filter(
        student_id=OuterRef("student_id"),
        academic_year=active_year,
    )
    if not scope.allows_all_stages:
        active_enrollments = active_enrollments.filter(
            section__grade_level__stage__in=scope.stages,
        )
    return queryset.filter(Exists(active_enrollments))
