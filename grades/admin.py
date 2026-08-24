from django.contrib import admin

from .models import (
    Assessment,
    StudentScore,
)


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "subject_display",
        "grade_level_display",
        "section",
        "term",
        "max_score",
        "assessment_date",
        "status",
        "created_by",
        "published_by",
        "published_at",
        "created_at",
    )

    list_filter = (
        "status",
        "term",
        "section__academic_year",
        "section__grade_level",
        "section",
        "grade_subject__subject",
        "assessment_date",
    )

    search_fields = (
        "title",
        "section__name",
        "section__grade_level__name",
        "grade_subject__subject__name",
        "created_by__username",
        "published_by__username",
    )

    list_select_related = (
        "section",
        "section__academic_year",
        "section__grade_level",
        "grade_subject",
        "grade_subject__subject",
        "term",
        "created_by",
        "published_by",
    )

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )

    ordering = (
        "-assessment_date",
        "-created_at",
    )

    date_hierarchy = "assessment_date"

    @admin.display(
        description="المادة",
        ordering="grade_subject__subject__name",
    )
    def subject_display(self, obj):
        return obj.grade_subject.subject.name

    @admin.display(
        description="الصف",
        ordering="section__grade_level__name",
    )
    def grade_level_display(self, obj):
        return obj.section.grade_level.name


@admin.register(StudentScore)
class StudentScoreAdmin(admin.ModelAdmin):
    list_display = (
        "student_display",
        "assessment",
        "subject_display",
        "section_display",
        "score",
        "max_score_display",
        "updated_by",
        "updated_at",
    )

    list_filter = (
        "assessment__status",
        "assessment__term",
        "assessment__section__academic_year",
        "assessment__section__grade_level",
        "assessment__section",
        "assessment__grade_subject__subject",
    )

    search_fields = (
        "enrollment__student__first_name",
        "enrollment__student__last_name",
        "enrollment__student__father_name",
        "enrollment__student__mother_name",
        "assessment__title",
        "assessment__grade_subject__subject__name",
        "updated_by__username",
    )

    list_select_related = (
        "assessment",
        "assessment__section",
        "assessment__section__grade_level",
        "assessment__grade_subject",
        "assessment__grade_subject__subject",
        "enrollment",
        "enrollment__student",
        "updated_by",
    )

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )

    ordering = (
        "-updated_at",
    )

    @admin.display(
        description="الطالب",
        ordering="enrollment__student__first_name",
    )
    def student_display(self, obj):
        return obj.enrollment.student.full_name

    @admin.display(
        description="المادة",
        ordering="assessment__grade_subject__subject__name",
    )
    def subject_display(self, obj):
        return obj.assessment.grade_subject.subject.name

    @admin.display(
        description="الشعبة",
        ordering="assessment__section__name",
    )
    def section_display(self, obj):
        return obj.assessment.section.name

    @admin.display(
        description="النهاية العظمى",
        ordering="assessment__max_score",
    )
    def max_score_display(self, obj):
        return obj.assessment.max_score