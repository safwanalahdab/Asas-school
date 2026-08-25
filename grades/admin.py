from django import forms
from django.contrib import admin

from .models import Assessment, AssessmentSection, ScoreAuditLog, StudentScore
from .services import record_score_audit


class FullCleanModelForm(forms.ModelForm):
    def _post_clean(self):
        super()._post_clean()
        if self.instance:
            self.instance.full_clean(exclude=self._get_validation_exclusions(), validate_unique=False)


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    form = FullCleanModelForm
    list_display = ("title", "grade_subject", "term", "max_score", "assessment_date", "created_by", "created_at")
    list_filter = ("term", "grade_subject__academic_year", "grade_subject__grade_level", "grade_subject__subject", "assessment_date")
    search_fields = ("title", "grade_subject__subject__name", "created_by__username")
    list_select_related = ("grade_subject__subject", "term", "created_by")
    readonly_fields = ("id", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        obj.full_clean()
        super().save_model(request, obj, form, change)


@admin.register(AssessmentSection)
class AssessmentSectionAdmin(admin.ModelAdmin):
    form = FullCleanModelForm
    list_display = ("assessment", "section", "status", "published_by", "published_at")
    list_filter = ("status", "section__academic_year", "section__grade_level", "section")
    search_fields = ("assessment__title", "section__name")
    list_select_related = ("assessment__grade_subject", "section", "published_by")
    readonly_fields = ("id", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        obj.full_clean()
        super().save_model(request, obj, form, change)


@admin.register(StudentScore)
class StudentScoreAdmin(admin.ModelAdmin):
    form = FullCleanModelForm
    list_display = ("student_display", "assessment", "recorded_section", "score", "updated_by", "updated_at")
    list_filter = ("assessment__term", "recorded_section", "assessment__grade_subject__subject")
    search_fields = ("enrollment__student__first_name", "enrollment__student__last_name", "assessment__title")
    list_select_related = ("assessment", "enrollment__student", "recorded_section", "updated_by")
    readonly_fields = ("id", "created_at", "updated_at")

    @admin.display(description="الطالب", ordering="enrollment__student__first_name")
    def student_display(self, obj):
        return obj.enrollment.student.full_name

    def save_model(self, request, obj, form, change):
        old_score = None
        if change:
            old_score = StudentScore.objects.get(pk=obj.pk).score
        obj.updated_by = request.user
        obj.full_clean()
        super().save_model(request, obj, form, change)
        record_score_audit(
            student_score=obj,
            old_score=old_score,
            actor=request.user,
            source=ScoreAuditLog.Source.ADMIN,
        )


@admin.register(ScoreAuditLog)
class ScoreAuditLogAdmin(admin.ModelAdmin):
    list_display = ("assessment", "enrollment", "recorded_section", "old_score", "new_score", "actor", "source", "created_at")
    list_filter = ("source", "recorded_section", "created_at")
    search_fields = ("assessment__title", "enrollment__student__first_name", "enrollment__student__last_name", "actor__username")
    readonly_fields = ("id", "assessment", "enrollment", "recorded_section", "old_score", "new_score", "actor", "source", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
