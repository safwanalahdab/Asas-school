from rest_framework.exceptions import PermissionDenied

from academics.supervisor_academic_scope import (
    can_access_grade_level,
    can_access_section,
    can_access_enrollment,
    is_stage_scoped_supervisor,
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
    if not is_stage_scoped_supervisor(user):
        return
    subject = assessment.grade_subject
    require_grade_level(user, subject.grade_level)
    links = AssessmentSection.objects.filter(assessment=assessment).select_related("section__grade_level")
    for link in links:
        if (link.section.grade_level_id != subject.grade_level_id
                or link.section.academic_year_id != subject.academic_year_id):
            raise PermissionDenied(DENIED)
        require_section(user, link.section)
    scores = StudentScore.objects.filter(assessment=assessment).select_related("recorded_section__grade_level")
    for score in scores:
        if not links.filter(section_id=score.recorded_section_id).exists():
            raise PermissionDenied(DENIED)
        require_section(user, score.recorded_section)
