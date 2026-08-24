from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from rest_framework.exceptions import (
    PermissionDenied,
    ValidationError,
)

from academics.models import Section
from teaching.models import TeacherAssignment

from .models import (
    Assessment,
    StudentScore,
)


User = get_user_model()

ZERO = Decimal("0")


def validate_assessment_scope(
    *,
    section,
    grade_subject,
    term,
    assessment_date=None,
):
    if (
        grade_subject.academic_year_id
        != section.academic_year_id
    ):
        raise ValidationError(
            {
                "grade_subject": (
                    "مادة الصف لا تتبع السنة الدراسية "
                    "الخاصة بالشعبة."
                )
            }
        )

    if (
        grade_subject.grade_level_id
        != section.grade_level_id
    ):
        raise ValidationError(
            {
                "grade_subject": (
                    "مادة الصف لا تتبع صف الشعبة المحددة."
                )
            }
        )

    if (
        term.academic_year_id
        != section.academic_year_id
    ):
        raise ValidationError(
            {
                "term": (
                    "الفصل الدراسي لا يتبع السنة "
                    "الدراسية الخاصة بالشعبة."
                )
            }
        )

    if assessment_date is not None:
        if not (
            term.start_date
            <= assessment_date
            <= term.end_date
        ):
            raise ValidationError(
                {
                    "assessment_date": (
                        "تاريخ التقييم يجب أن يقع ضمن "
                        "الفصل الدراسي المحدد."
                    )
                }
            )


def teacher_has_active_assignment(
    *,
    teacher,
    section,
    grade_subject,
):
    today = timezone.localdate()

    return (
        TeacherAssignment.objects
        .filter(
            teacher=teacher,
            section=section,
            grade_subject=grade_subject,
            start_date__lte=today,
        )
        .filter(
            Q(
                end_date__isnull=True,
            )
            | Q(
                end_date__gte=today,
            )
        )
        .exists()
    )


def ensure_actor_can_manage_scope(
    *,
    actor,
    section,
    grade_subject,
):
    if actor.is_superuser:
        return

    if actor.role in {
        User.Role.SCHOOL_ADMIN,
        User.Role.SUPERVISOR,
    }:
        return

    if actor.role == User.Role.TEACHER:
        if teacher_has_active_assignment(
            teacher=actor,
            section=section,
            grade_subject=grade_subject,
        ):
            return

        raise PermissionDenied(
            {
                "code": "GRADE_ASSIGNMENT_REQUIRED",
                "detail": (
                    "لا يمكنك إدارة علامات هذه المادة "
                    "والشعبة لأنك غير مكلّف بها حاليًا."
                ),
            }
        )

    raise PermissionDenied(
        {
            "code": "GRADES_ACCESS_DENIED",
            "detail": (
                "ليس لديك صلاحية لإدارة العلامات."
            ),
        }
    )


def _validate_assessment_values(
    *,
    title,
    max_score,
):
    if not title or not title.strip():
        raise ValidationError(
            {
                "title": (
                    "عنوان التقييم مطلوب."
                )
            }
        )

    if max_score <= ZERO:
        raise ValidationError(
            {
                "max_score": (
                    "النهاية العظمى يجب أن تكون "
                    "أكبر من صفر."
                )
            }
        )


def _ensure_assessment_not_duplicate(
    *,
    section,
    grade_subject,
    term,
    title,
    assessment_date,
    allow_duplicate=False,
    exclude_assessment_id=None,
):
    if allow_duplicate:
        return

    queryset = Assessment.objects.filter(
        section=section,
        grade_subject=grade_subject,
        term=term,
        assessment_date=assessment_date,
        title__iexact=title.strip(),
    )

    if exclude_assessment_id is not None:
        queryset = queryset.exclude(
            pk=exclude_assessment_id,
        )

    if queryset.exists():
        raise ValidationError(
            {
                "detail": (
                    "يوجد تقييم مطابق بنفس المادة "
                    "والشعبة والفصل والتاريخ."
                )
            }
        )


@transaction.atomic
def create_assessment(
    *,
    section,
    grade_subject,
    term,
    title,
    max_score,
    assessment_date,
    actor,
    allow_duplicate=False,
):
    validate_assessment_scope(
        section=section,
        grade_subject=grade_subject,
        term=term,
        assessment_date=assessment_date,
    )

    ensure_actor_can_manage_scope(
        actor=actor,
        section=section,
        grade_subject=grade_subject,
    )

    _validate_assessment_values(
        title=title,
        max_score=max_score,
    )

    _ensure_assessment_not_duplicate(
        section=section,
        grade_subject=grade_subject,
        term=term,
        title=title,
        assessment_date=assessment_date,
        allow_duplicate=allow_duplicate,
    )

    assessment = Assessment.objects.create(
        section=section,
        grade_subject=grade_subject,
        term=term,
        title=title.strip(),
        max_score=max_score,
        assessment_date=assessment_date,
        status=Assessment.Status.DRAFT,
        created_by=actor,
    )

    return assessment


@transaction.atomic
def update_assessment(
    *,
    assessment,
    actor,
    title=None,
    max_score=None,
    assessment_date=None,
    allow_duplicate=False,
):
    assessment = (
        Assessment.objects
        .select_for_update()
        .select_related(
            "section",
            "grade_subject",
            "term",
        )
        .get(
            pk=assessment.pk,
        )
    )

    ensure_actor_can_manage_scope(
        actor=actor,
        section=assessment.section,
        grade_subject=assessment.grade_subject,
    )

    new_title = (
        title
        if title is not None
        else assessment.title
    )

    new_max_score = (
        max_score
        if max_score is not None
        else assessment.max_score
    )

    new_assessment_date = (
        assessment_date
        if assessment_date is not None
        else assessment.assessment_date
    )

    _validate_assessment_values(
        title=new_title,
        max_score=new_max_score,
    )

    validate_assessment_scope(
        section=assessment.section,
        grade_subject=assessment.grade_subject,
        term=assessment.term,
        assessment_date=new_assessment_date,
    )

    _ensure_assessment_not_duplicate(
        section=assessment.section,
        grade_subject=assessment.grade_subject,
        term=assessment.term,
        title=new_title,
        assessment_date=new_assessment_date,
        allow_duplicate=allow_duplicate,
        exclude_assessment_id=assessment.id,
    )

    highest_score = (
        assessment.scores
        .filter(
            score__isnull=False,
        )
        .order_by(
            "-score",
        )
        .values_list(
            "score",
            flat=True,
        )
        .first()
    )

    if (
        highest_score is not None
        and new_max_score < highest_score
    ):
        raise ValidationError(
            {
                "max_score": (
                    "لا يمكن تخفيض النهاية العظمى "
                    "إلى قيمة أقل من علامة موجودة "
                    f"فعليًا ({highest_score})."
                )
            }
        )

    assessment.title = new_title.strip()
    assessment.max_score = new_max_score
    assessment.assessment_date = (
        new_assessment_date
    )

    assessment.save(
        update_fields=[
            "title",
            "max_score",
            "assessment_date",
            "updated_at",
        ]
    )

    return assessment


@transaction.atomic
def delete_assessment(
    *,
    assessment,
    actor,
):
    assessment = (
        Assessment.objects
        .select_for_update()
        .select_related(
            "section",
            "grade_subject",
        )
        .get(
            pk=assessment.pk,
        )
    )

    ensure_actor_can_manage_scope(
        actor=actor,
        section=assessment.section,
        grade_subject=assessment.grade_subject,
    )

    if (
        assessment.status
        != Assessment.Status.DRAFT
    ):
        raise ValidationError(
            {
                "detail": (
                    "لا يمكن حذف تقييم تم اعتماده "
                    "ونشره مسبقًا."
                )
            }
        )

    if assessment.scores.exists():
        raise ValidationError(
            {
                "detail": (
                    "لا يمكن حذف التقييم لأنه مرتبط "
                    "بسجلات علامات للطلاب."
                )
            }
        )

    assessment.delete()


@transaction.atomic
def create_assessments_for_grade(
    *,
    grade_subject,
    term,
    title,
    max_score,
    assessment_date,
    actor,
    allow_duplicate=False,
):
    if not actor.is_superuser and actor.role not in {
        User.Role.SCHOOL_ADMIN,
        User.Role.SUPERVISOR,
    }:
        raise PermissionDenied(
            {
                "code": "GRADE_WIDE_CREATE_DENIED",
                "detail": (
                    "إنشاء تقييم لكل شعب الصف متاح "
                    "للإدارة والموجّه التربوي فقط."
                ),
            }
        )

    if (
        term.academic_year_id
        != grade_subject.academic_year_id
    ):
        raise ValidationError(
            {
                "term": (
                    "الفصل الدراسي لا يتبع سنة "
                    "مادة الصف المحددة."
                )
            }
        )

    _validate_assessment_values(
        title=title,
        max_score=max_score,
    )

    if not (
        term.start_date
        <= assessment_date
        <= term.end_date
    ):
        raise ValidationError(
            {
                "assessment_date": (
                    "تاريخ التقييم يجب أن يقع ضمن "
                    "الفصل الدراسي المحدد."
                )
            }
        )

    sections = (
        Section.objects
        .filter(
            academic_year=(
                grade_subject.academic_year
            ),
            grade_level=(
                grade_subject.grade_level
            ),
            is_active=True,
        )
        .order_by(
            "name",
        )
    )

    if not sections.exists():
        raise ValidationError(
            {
                "detail": (
                    "لا توجد شعب فعالة لهذا الصف "
                    "في السنة الدراسية المحددة."
                )
            }
        )

    created_assessments = []

    for section in sections:
        _ensure_assessment_not_duplicate(
            section=section,
            grade_subject=grade_subject,
            term=term,
            title=title,
            assessment_date=assessment_date,
            allow_duplicate=allow_duplicate,
        )

        assessment = Assessment.objects.create(
            section=section,
            grade_subject=grade_subject,
            term=term,
            title=title.strip(),
            max_score=max_score,
            assessment_date=assessment_date,
            status=Assessment.Status.DRAFT,
            created_by=actor,
        )

        created_assessments.append(
            assessment
        )

    return created_assessments


def _validate_score_record(
    *,
    assessment,
    enrollment,
    score,
):
    if (
        enrollment.academic_year_id
        != assessment.section.academic_year_id
    ):
        raise ValidationError(
            {
                "enrollment": (
                    "تسجيل الطالب لا يتبع السنة "
                    "الدراسية الخاصة بالتقييم."
                )
            }
        )

    if (
        enrollment.section_id
        != assessment.section_id
    ):
        raise ValidationError(
            {
                "enrollment": (
                    "الطالب لا يتبع شعبة التقييم."
                )
            }
        )

    if score is None:
        return

    if score < ZERO:
        raise ValidationError(
            {
                "score": (
                    "العلامة لا يمكن أن تكون سالبة."
                )
            }
        )

    if score > assessment.max_score:
        raise ValidationError(
            {
                "score": (
                    "العلامة لا يمكن أن تتجاوز "
                    "النهاية العظمى "
                    f"({assessment.max_score})."
                )
            }
        )


@transaction.atomic
def save_assessment_scores_bulk(
    *,
    assessment,
    records,
    actor,
):
    assessment = (
        Assessment.objects
        .select_for_update()
        .select_related(
            "section",
            "grade_subject",
        )
        .get(
            pk=assessment.pk,
        )
    )

    ensure_actor_can_manage_scope(
        actor=actor,
        section=assessment.section,
        grade_subject=assessment.grade_subject,
    )

    if not records:
        raise ValidationError(
            {
                "records": (
                    "يجب إرسال علامة طالب واحد "
                    "على الأقل."
                )
            }
        )

    enrollment_ids = [
        record["enrollment"].id
        for record in records
    ]

    if (
        len(enrollment_ids)
        != len(set(enrollment_ids))
    ):
        raise ValidationError(
            {
                "records": (
                    "لا يمكن إرسال الطالب نفسه "
                    "أكثر من مرة ضمن الطلب."
                )
            }
        )

    for record in records:
        _validate_score_record(
            assessment=assessment,
            enrollment=record["enrollment"],
            score=record.get("score"),
        )

    saved_scores = []

    for record in records:
        student_score, _ = (
            StudentScore.objects.update_or_create(
                assessment=assessment,
                enrollment=record["enrollment"],
                defaults={
                    "score": record.get(
                        "score"
                    ),
                    "updated_by": actor,
                },
            )
        )

        saved_scores.append(
            student_score
        )

    return saved_scores


def _ensure_actor_can_publish(
    *,
    actor,
):
    if actor.is_superuser:
        return

    if actor.role in {
        User.Role.SCHOOL_ADMIN,
        User.Role.SUPERVISOR,
    }:
        return

    raise PermissionDenied(
        {
            "code": "GRADES_PUBLISH_DENIED",
            "detail": (
                "اعتماد ونشر النتائج متاح للإدارة "
                "والموجّه التربوي فقط."
            ),
        }
    )


@transaction.atomic
def publish_section_assessments(
    *,
    section,
    term,
    actor,
):
    _ensure_actor_can_publish(
        actor=actor,
    )

    if (
        section.academic_year_id
        != term.academic_year_id
    ):
        raise ValidationError(
            {
                "term": (
                    "الفصل الدراسي لا يتبع السنة "
                    "الدراسية الخاصة بالشعبة."
                )
            }
        )

    published_at = timezone.now()

    updated_count = (
        Assessment.objects
        .filter(
            section=section,
            term=term,
            status=Assessment.Status.DRAFT,
        )
        .update(
            status=Assessment.Status.PUBLISHED,
            published_by=actor,
            published_at=published_at,
            updated_at=published_at,
        )
    )

    return updated_count


@transaction.atomic
def publish_grade_assessments(
    *,
    grade_level,
    term,
    actor,
):
    _ensure_actor_can_publish(
        actor=actor,
    )

    published_at = timezone.now()

    updated_count = (
        Assessment.objects
        .filter(
            section__academic_year=(
                term.academic_year
            ),
            section__grade_level=grade_level,
            term=term,
            status=Assessment.Status.DRAFT,
        )
        .update(
            status=Assessment.Status.PUBLISHED,
            published_by=actor,
            published_at=published_at,
            updated_at=published_at,
        )
    )

    return updated_count