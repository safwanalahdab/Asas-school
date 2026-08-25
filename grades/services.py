from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from academics.models import Section
from teaching.models import TeacherAssignment

from .models import Assessment, AssessmentSection, ScoreAuditLog, StudentScore
from .selectors import get_enrollment_section_id_on_date

User = get_user_model()
ZERO = Decimal("0")


def record_score_audit(*, student_score, old_score, actor, source):
    return ScoreAuditLog.objects.create(
        assessment=student_score.assessment,
        enrollment=student_score.enrollment,
        recorded_section=student_score.recorded_section,
        old_score=old_score,
        new_score=student_score.score,
        actor=actor,
        source=source,
    )


def validate_assessment_scope(*, section, grade_subject, term, assessment_date=None):
    if grade_subject.academic_year_id != section.academic_year_id:
        raise ValidationError({"grade_subject": "مادة الصف لا تتبع السنة الدراسية الخاصة بالشعبة."})
    if grade_subject.grade_level_id != section.grade_level_id:
        raise ValidationError({"grade_subject": "مادة الصف لا تتبع صف الشعبة المحددة."})
    if term.academic_year_id != section.academic_year_id:
        raise ValidationError({"term": "الفصل الدراسي لا يتبع السنة الدراسية الخاصة بالشعبة."})
    if assessment_date is not None and not term.start_date <= assessment_date <= term.end_date:
        raise ValidationError({"assessment_date": "تاريخ التقييم يجب أن يقع ضمن الفصل الدراسي المحدد."})


def teacher_has_active_assignment(*, teacher, section, grade_subject):
    today = timezone.localdate()
    return TeacherAssignment.objects.filter(
        teacher=teacher, section=section, grade_subject=grade_subject, start_date__lte=today
    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=today)).exists()


def ensure_actor_can_manage_scope(*, actor, section, grade_subject):
    if actor.is_superuser or actor.role in {User.Role.SCHOOL_ADMIN, User.Role.SUPERVISOR}:
        return
    if actor.role == User.Role.TEACHER and teacher_has_active_assignment(
        teacher=actor, section=section, grade_subject=grade_subject
    ):
        return
    raise PermissionDenied({"code": "GRADE_ASSIGNMENT_REQUIRED", "detail": "ليس لديك تكليف فعال لإدارة هذه المادة والشعبة."})


def _validate_definition(*, title, max_score, term, assessment_date):
    if not title or not title.strip():
        raise ValidationError({"title": "عنوان التقييم مطلوب."})
    if max_score <= ZERO:
        raise ValidationError({"max_score": "النهاية العظمى يجب أن تكون أكبر من صفر."})
    if not term.start_date <= assessment_date <= term.end_date:
        raise ValidationError({"assessment_date": "تاريخ التقييم يجب أن يقع ضمن الفصل الدراسي المحدد."})


def _ensure_not_duplicate(*, sections, grade_subject, term, title, assessment_date, allow_duplicate=False, exclude_id=None):
    if allow_duplicate:
        return
    query = Assessment.objects.filter(
        assessment_sections__section__in=sections,
        grade_subject=grade_subject,
        term=term,
        title__iexact=title.strip(),
        assessment_date=assessment_date,
    )
    if exclude_id:
        query = query.exclude(pk=exclude_id)
    if query.exists():
        raise ValidationError({"detail": "يوجد تقييم مطابق في إحدى الشعب المحددة."})


@transaction.atomic
def create_assessment(*, section, grade_subject, term, title, max_score, assessment_date, actor, allow_duplicate=False):
    validate_assessment_scope(section=section, grade_subject=grade_subject, term=term, assessment_date=assessment_date)
    ensure_actor_can_manage_scope(actor=actor, section=section, grade_subject=grade_subject)
    _validate_definition(title=title, max_score=max_score, term=term, assessment_date=assessment_date)
    _ensure_not_duplicate(sections=[section], grade_subject=grade_subject, term=term, title=title, assessment_date=assessment_date, allow_duplicate=allow_duplicate)
    assessment = Assessment.objects.create(
        grade_subject=grade_subject, term=term, title=title.strip(), max_score=max_score,
        assessment_date=assessment_date, created_by=actor,
    )
    AssessmentSection.objects.create(assessment=assessment, section=section)
    return assessment


@transaction.atomic
def create_assessments_for_grade(*, grade_subject, term, title, max_score, assessment_date, actor, allow_duplicate=False):
    if not actor.is_superuser and actor.role not in {User.Role.SCHOOL_ADMIN, User.Role.SUPERVISOR}:
        raise PermissionDenied({"code": "GRADE_WIDE_CREATE_DENIED", "detail": "إنشاء تقييم لصف كامل متاح للإدارة والموجّه التربوي فقط."})
    if term.academic_year_id != grade_subject.academic_year_id:
        raise ValidationError({"term": "الفصل الدراسي لا يتبع سنة مادة الصف المحددة."})
    _validate_definition(title=title, max_score=max_score, term=term, assessment_date=assessment_date)
    sections = list(Section.objects.filter(
        academic_year=grade_subject.academic_year, grade_level=grade_subject.grade_level, is_active=True
    ).order_by("name"))
    if not sections:
        raise ValidationError({"detail": "لا توجد شعب فعالة لهذا الصف."})
    _ensure_not_duplicate(sections=sections, grade_subject=grade_subject, term=term, title=title, assessment_date=assessment_date, allow_duplicate=allow_duplicate)
    assessment = Assessment.objects.create(
        grade_subject=grade_subject, term=term, title=title.strip(), max_score=max_score,
        assessment_date=assessment_date, created_by=actor,
    )
    AssessmentSection.objects.bulk_create([
        AssessmentSection(assessment=assessment, section=section) for section in sections
    ])
    return assessment


@transaction.atomic
def update_assessment(*, assessment, actor, title=None, max_score=None, assessment_date=None, allow_duplicate=False):
    assessment = Assessment.objects.select_for_update().select_related("grade_subject", "term").get(pk=assessment.pk)
    links = list(AssessmentSection.objects.select_for_update().filter(assessment=assessment).select_related("section"))
    for link in links:
        ensure_actor_can_manage_scope(actor=actor, section=link.section, grade_subject=assessment.grade_subject)
    if any(link.status == AssessmentSection.Status.PUBLISHED for link in links):
        raise ValidationError({"detail": "لا يمكن تعديل تعريف تقييم نُشر في إحدى الشعب."})
    new_title = assessment.title if title is None else title
    new_max = assessment.max_score if max_score is None else max_score
    new_date = assessment.assessment_date if assessment_date is None else assessment_date
    _validate_definition(title=new_title, max_score=new_max, term=assessment.term, assessment_date=new_date)
    _ensure_not_duplicate(sections=[x.section for x in links], grade_subject=assessment.grade_subject, term=assessment.term, title=new_title, assessment_date=new_date, allow_duplicate=allow_duplicate, exclude_id=assessment.id)
    highest = assessment.scores.exclude(score=None).order_by("-score").values_list("score", flat=True).first()
    if highest is not None and new_max < highest:
        raise ValidationError({"max_score": "لا يمكن جعل النهاية العظمى أقل من علامة موجودة."})
    assessment.title, assessment.max_score, assessment.assessment_date = new_title.strip(), new_max, new_date
    assessment.save(update_fields=["title", "max_score", "assessment_date", "updated_at"])
    return assessment


@transaction.atomic
def delete_assessment(*, assessment, actor):
    assessment = Assessment.objects.select_for_update().select_related("grade_subject").get(pk=assessment.pk)
    links = list(AssessmentSection.objects.select_for_update().filter(assessment=assessment).select_related("section"))
    for link in links:
        ensure_actor_can_manage_scope(actor=actor, section=link.section, grade_subject=assessment.grade_subject)
    if any(link.status == AssessmentSection.Status.PUBLISHED for link in links):
        raise ValidationError({"detail": "لا يمكن حذف تقييم منشور."})
    if StudentScore.objects.select_for_update().filter(assessment=assessment).exists():
        raise ValidationError({"detail": "لا يمكن حذف تقييم مرتبط بعلامات طلاب."})
    assessment.delete()


def resolve_assessment_section(*, assessment, section=None):
    links = AssessmentSection.objects.filter(assessment=assessment).select_related("section")
    if section is not None:
        link = links.filter(section=section).first()
        if not link:
            raise ValidationError({"section": "الشعبة ليست ضمن نطاق هذا التقييم."})
        return link
    links = list(links[:2])
    if len(links) != 1:
        raise ValidationError({"section": "يجب تحديد الشعبة صراحة لهذا التقييم."})
    return links[0]


def _validate_score(*, assessment, section, enrollment, score):
    if (
        enrollment.academic_year_id != section.academic_year_id
        or get_enrollment_section_id_on_date(
            enrollment=enrollment,
            target_date=assessment.assessment_date,
        ) != section.id
    ):
        raise ValidationError({"enrollment": "الطالب لم يكن يتبع شعبة التقييم في تاريخ التقييم."})
    if enrollment.enrollment_date > assessment.assessment_date:
        raise ValidationError({"enrollment": "الطالب التحق بعد تاريخ هذا التقييم."})
    if score is not None and (score < ZERO or score > assessment.max_score):
        raise ValidationError({"score": "العلامة يجب أن تكون بين صفر والنهاية العظمى."})


@transaction.atomic
def save_assessment_scores_bulk(*, assessment, section, records, actor, source=ScoreAuditLog.Source.API):
    assessment = Assessment.objects.select_for_update().select_related("grade_subject").get(pk=assessment.pk)
    link = AssessmentSection.objects.select_for_update().select_related("section").get(assessment=assessment, section=section)
    ensure_actor_can_manage_scope(actor=actor, section=link.section, grade_subject=assessment.grade_subject)
    ids = [record["enrollment"].id for record in records]
    if not ids or len(ids) != len(set(ids)):
        raise ValidationError({"records": "يجب إرسال سجلات غير مكررة لطالب واحد على الأقل."})
    existing = {x.enrollment_id: x for x in StudentScore.objects.select_for_update().filter(assessment=assessment, enrollment_id__in=ids)}
    saved = []
    for record in records:
        enrollment, value = record["enrollment"], record.get("score")
        current = existing.get(enrollment.id)
        if current is None:
            _validate_score(assessment=assessment, section=section, enrollment=enrollment, score=value)
            current = StudentScore.objects.create(assessment=assessment, enrollment=enrollment, recorded_section=section, score=value, updated_by=actor)
            old = None
        else:
            if current.recorded_section_id != section.id:
                raise ValidationError({"enrollment": "العلامة التاريخية مسجلة تحت شعبة أخرى ولا يجوز نقلها ضمنيًا."})
            if value is not None and (value < ZERO or value > assessment.max_score):
                raise ValidationError({"score": "العلامة يجب أن تكون بين صفر والنهاية العظمى."})
            old = current.score
            current.score, current.updated_by = value, actor
            current.save(update_fields=["score", "updated_by", "updated_at"])
        record_score_audit(
            student_score=current,
            old_score=old,
            actor=actor,
            source=source,
        )
        saved.append(current)
    return saved


def _ensure_can_publish(actor):
    if not actor.is_superuser and actor.role not in {User.Role.SCHOOL_ADMIN, User.Role.SUPERVISOR}:
        raise PermissionDenied({"code": "GRADES_PUBLISH_DENIED", "detail": "نشر النتائج متاح للإدارة والموجّه التربوي فقط."})


@transaction.atomic
def publish_section_assessments(*, section, term, actor):
    _ensure_can_publish(actor)
    if section.academic_year_id != term.academic_year_id:
        raise ValidationError({"term": "الفصل الدراسي لا يتبع سنة الشعبة."})
    now, today = timezone.now(), timezone.localdate()
    links = AssessmentSection.objects.select_for_update().filter(section=section, assessment__term=term, assessment__assessment_date__lte=today, status=AssessmentSection.Status.DRAFT)
    count = links.update(status=AssessmentSection.Status.PUBLISHED, published_by=actor, published_at=now, updated_at=now)
    future = AssessmentSection.objects.filter(section=section, assessment__term=term, assessment__assessment_date__gt=today, status=AssessmentSection.Status.DRAFT).count()
    return {"published_count": count, "skipped_future_count": future}


@transaction.atomic
def publish_grade_assessments(*, grade_level, term, actor):
    _ensure_can_publish(actor)
    now, today = timezone.now(), timezone.localdate()
    base = AssessmentSection.objects.select_for_update().filter(section__academic_year=term.academic_year, section__grade_level=grade_level, assessment__term=term, status=AssessmentSection.Status.DRAFT)
    future = base.filter(assessment__assessment_date__gt=today).count()
    count = base.filter(assessment__assessment_date__lte=today).update(status=AssessmentSection.Status.PUBLISHED, published_by=actor, published_at=now, updated_at=now)
    return {"published_count": count, "skipped_future_count": future}
