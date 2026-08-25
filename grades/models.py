import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from academics.models import GradeSubject, Section, Term
from students.models import Enrollment


class Assessment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    grade_subject = models.ForeignKey(GradeSubject, on_delete=models.PROTECT, related_name="assessments")
    term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="assessments")
    title = models.CharField(max_length=150)
    max_score = models.DecimalField(max_digits=7, decimal_places=2)
    assessment_date = models.DateField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_assessments")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "grades_assessment"
        ordering = ["-assessment_date", "-created_at"]
        constraints = [models.CheckConstraint(condition=models.Q(max_score__gt=0), name="gr_assess_max_positive")]
        indexes = [models.Index(fields=["grade_subject", "term"], name="gr_assess_sub_term_idx")]

    def clean(self):
        errors = {}
        if self.term_id and self.grade_subject_id:
            if self.term.academic_year_id != self.grade_subject.academic_year_id:
                errors["term"] = "الفصل الدراسي لا يتبع سنة مادة الصف المحددة."
            if not self.term.start_date <= self.assessment_date <= self.term.end_date:
                errors["assessment_date"] = "تاريخ التقييم يجب أن يقع ضمن الفصل الدراسي المحدد."
        if self.max_score is not None and self.max_score <= 0:
            errors["max_score"] = "النهاية العظمى يجب أن تكون أكبر من صفر."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.title} - {self.grade_subject.subject}"


class AssessmentSection(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "مسودة"
        PUBLISHED = "published", "منشور"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="assessment_sections")
    section = models.ForeignKey(Section, on_delete=models.PROTECT, related_name="assessment_sections")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="published_assessment_sections", null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "grades_assessment_section"
        ordering = ["section__name"]
        constraints = [
            models.UniqueConstraint(fields=["assessment", "section"], name="gr_assess_section_unique"),
            models.CheckConstraint(
                condition=(models.Q(status="draft", published_by__isnull=True, published_at__isnull=True) | models.Q(status="published", published_by__isnull=False, published_at__isnull=False)),
                name="gr_assess_sec_publish_consistent",
            ),
        ]
        indexes = [models.Index(fields=["section", "status"], name="gr_assess_sec_st_idx")]

    def clean(self):
        errors = {}
        if self.assessment_id and self.section_id:
            subject = self.assessment.grade_subject
            if subject.academic_year_id != self.section.academic_year_id:
                errors["section"] = "الشعبة لا تتبع السنة الدراسية الخاصة بالتقييم."
            elif subject.grade_level_id != self.section.grade_level_id:
                errors["section"] = "الشعبة لا تتبع صف مادة التقييم."
            if self.assessment.term.academic_year_id != self.section.academic_year_id:
                errors["section"] = "الشعبة لا تتبع سنة الفصل الدراسي الخاص بالتقييم."
        published = self.status == self.Status.PUBLISHED
        if published != bool(self.published_by_id and self.published_at):
            errors["status"] = "بيانات نشر التقييم في الشعبة غير متسقة."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.assessment} - {self.section}"


class StudentScore(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(Assessment, on_delete=models.PROTECT, related_name="scores")
    enrollment = models.ForeignKey(Enrollment, on_delete=models.PROTECT, related_name="assessment_scores")
    recorded_section = models.ForeignKey(Section, on_delete=models.PROTECT, related_name="recorded_student_scores")
    score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="updated_student_scores")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "grades_student_score"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["assessment", "enrollment"], name="gr_score_unique_assess_enr"),
            models.CheckConstraint(condition=models.Q(score__isnull=True) | models.Q(score__gte=0), name="gr_score_nonnegative"),
        ]

    def clean(self):
        errors = {}
        if self.assessment_id and self.recorded_section_id and not AssessmentSection.objects.filter(assessment_id=self.assessment_id, section_id=self.recorded_section_id).exists():
            errors["recorded_section"] = "الشعبة ليست ضمن نطاق هذا التقييم."
        if self.enrollment_id and self.recorded_section_id and self.enrollment.academic_year_id != self.recorded_section.academic_year_id:
            errors["enrollment"] = "تسجيل الطالب لا يتبع سنة شعبة العلامة."
        if self.score is not None:
            if self.score < 0:
                errors["score"] = "العلامة لا يمكن أن تكون سالبة."
            elif self.assessment_id and self.score > self.assessment.max_score:
                errors["score"] = "العلامة لا يمكن أن تتجاوز النهاية العظمى."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.enrollment.student} - {self.assessment} - {self.score}"


class ScoreAuditLog(models.Model):
    class Source(models.TextChoices):
        API = "api", "واجهة API"
        ADMIN = "admin", "لوحة الإدارة"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(Assessment, on_delete=models.PROTECT, related_name="score_audit_logs")
    enrollment = models.ForeignKey(Enrollment, on_delete=models.PROTECT, related_name="score_audit_logs")
    recorded_section = models.ForeignKey(Section, on_delete=models.PROTECT, related_name="score_audit_logs")
    old_score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    new_score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="score_audit_logs")
    source = models.CharField(max_length=20, choices=Source.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "grades_score_audit_log"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["assessment", "enrollment", "created_at"], name="gr_score_audit_hist_idx")]

    def __str__(self):
        return f"{self.enrollment.student}: {self.old_score} → {self.new_score}"
