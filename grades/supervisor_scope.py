from rest_framework.exceptions import PermissionDenied

from academics.supervisor_academic_scope import (
    can_access_grade_level,
    can_access_section,
    can_access_enrollment,
    scope_allows_stage,
    supervisor_academic_scope_for,
)
from .models import AssessmentSection, StudentScore


DENIED = {
    "code": "SUPERVISOR_ACADEMIC_SCOPE_DENIED",
    "detail": "المورد المحدد خارج نطاق مراحل الموجّه.",
}


def require_grade_level(user, grade_level):
    if not can_access_grade_level(user, grade_level):
        raise PermissionDenied(DENIED)


def require_section(user, section):
    if not can_access_section(user, section):
        raise PermissionDenied(DENIED)


def require_enrollment(user, enrollment):
    if not can_access_enrollment(user, enrollment):
        raise PermissionDenied(DENIED)


def require_assessment(user, assessment):
    # Load the scope once; the require_* helpers would each reload it.
    scope = supervisor_academic_scope_for(user)
    if not scope.applies:
        return
    subject = assessment.grade_subject
    if not scope_allows_stage(scope, subject.grade_level.stage):
        raise PermissionDenied(DENIED)
    # Every linked section must sit in the subject's grade level, so it shares
    # the stage already checked above; per-section scope checks are redundant.
    links = AssessmentSection.objects.filter(assessment=assessment)
    if links.exclude(
        section__grade_level_id=subject.grade_level_id,
        section__academic_year_id=subject.academic_year_id,
    ).exists():
        raise PermissionDenied(DENIED)
    # Scores are scoped by their historical recorded_section, which must be linked.
    if StudentScore.objects.filter(assessment=assessment).exclude(
        recorded_section_id__in=links.values("section_id"),
    ).exists():
        raise PermissionDenied(DENIED)
