from django.db.models import Q
from django.utils import timezone

from teaching.models import TeacherAssignment


def teacher_student_scope_applies(user):
    return bool(
        user is not None
        and getattr(user, "is_authenticated", False)
        and not getattr(user, "is_superuser", False)
        and getattr(user, "role", None) == "teacher"
    )


def _teacher_scope_assignments(user, *, on_date=None):
    on_date = on_date or timezone.localdate()
    return TeacherAssignment.objects.filter(teacher=user).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=on_date)
    )


def filter_sections_by_teacher_scope(queryset, user, *, on_date=None):
    if not teacher_student_scope_applies(user):
        return queryset
    assignments = _teacher_scope_assignments(user, on_date=on_date)
    return queryset.filter(teacher_assignments__in=assignments).distinct()


def filter_enrollments_by_teacher_scope(queryset, user, *, on_date=None):
    if not teacher_student_scope_applies(user):
        return queryset
    assignments = _teacher_scope_assignments(user, on_date=on_date)
    return queryset.filter(
        section__teacher_assignments__in=assignments,
    ).distinct()


def filter_students_by_teacher_scope(queryset, user, *, on_date=None):
    if not teacher_student_scope_applies(user):
        return queryset
    assignments = _teacher_scope_assignments(user, on_date=on_date)
    return queryset.filter(
        enrollments__section__teacher_assignments__in=assignments,
    ).distinct()


def can_teacher_access_section(user, section, *, on_date=None):
    if not teacher_student_scope_applies(user):
        return True
    return filter_sections_by_teacher_scope(
        type(section).objects.filter(pk=section.pk),
        user,
        on_date=on_date,
    ).exists()


def can_teacher_access_enrollment(user, enrollment, *, on_date=None):
    if not teacher_student_scope_applies(user):
        return True
    return filter_enrollments_by_teacher_scope(
        type(enrollment).objects.filter(pk=enrollment.pk),
        user,
        on_date=on_date,
    ).exists()
