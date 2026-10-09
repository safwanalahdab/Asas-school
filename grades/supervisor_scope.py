from django.db.models import Exists, F, OuterRef
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


def require_grade_level(user, grade_level, *, scope=None):
    """Pass an already-loaded scope to avoid reloading it per call."""
    if scope is None:
        if not can_access_grade_level(user, grade_level):
            raise PermissionDenied(DENIED)
        return
    _require_stage(scope, lambda: grade_level.stage)


def _require_stage(scope, get_stage):
    # Resolve FK relations only for selected-stage scopes, like can_access_*.
    if not scope.applies or scope.allows_all_stages:
        return
    if not scope_allows_stage(scope, get_stage()):
        raise PermissionDenied(DENIED)


def require_section(user, section, *, scope=None):
    """Pass an already-loaded scope to avoid reloading it per call."""
    if scope is None:
        if not can_access_section(user, section):
            raise PermissionDenied(DENIED)
        return
    _require_stage(scope, lambda: section.grade_level.stage)


def require_enrollment(user, enrollment):
    if not can_access_enrollment(user, enrollment):
        raise PermissionDenied(DENIED)


def require_enrollments(user, enrollments, *, scope=None):
    """Check many enrollments against one scope load; keeps the first denial."""
    if scope is None:
        scope = supervisor_academic_scope_for(user)
    for enrollment in enrollments:
        _require_stage(scope, lambda: enrollment.section.grade_level.stage)


def require_assessment(user, assessment, *, scope=None):
    # Load the scope once; the require_* helpers would each reload it.
    if scope is None:
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


def require_assessments(user, assessments, *, scope=None):
    """Apply require_assessment to many assessments with a fixed query count.

    ``assessments`` is only evaluated for applicable scopes, so a lazy queryset
    costs nothing for other users. Select ``grade_subject__grade_level`` on it
    to keep the stage check in memory.
    """
    if scope is None:
        scope = supervisor_academic_scope_for(user)
    if not scope.applies:
        return
    assessments = list(assessments)
    if not assessments:
        return
    for assessment in assessments:
        if not scope_allows_stage(scope, assessment.grade_subject.grade_level.stage):
            raise PermissionDenied(DENIED)
    assessment_ids = [assessment.pk for assessment in assessments]
    # Same per-assessment rules as require_assessment, correlated in SQL.
    if AssessmentSection.objects.filter(assessment_id__in=assessment_ids).exclude(
        section__grade_level_id=F("assessment__grade_subject__grade_level_id"),
        section__academic_year_id=F("assessment__grade_subject__academic_year_id"),
    ).exists():
        raise PermissionDenied(DENIED)
    linked_section = AssessmentSection.objects.filter(
        assessment_id=OuterRef("assessment_id"),
        section_id=OuterRef("recorded_section_id"),
    )
    if StudentScore.objects.filter(assessment_id__in=assessment_ids).filter(
        ~Exists(linked_section),
    ).exists():
        raise PermissionDenied(DENIED)
