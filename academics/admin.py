from django.contrib import admin

from .models import (
    AcademicYear,
    Term,
    GradeLevel,
    Section,
    Subject,
    GradeSubject,
)


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "start_date",
        "end_date",
        "status",
        "created_at",
    )

    list_filter = (
        "status",
    )

    ordering = (
        "-start_date",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = (
        "academic_year",
        "number",
        "start_date",
        "end_date",
        "status",
    )

    list_filter = (
        "status",
        "number",
        "academic_year",
    )

    ordering = (
        "-academic_year__start_date",
        "number",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "academic_year",
    )


@admin.register(GradeLevel)
class GradeLevelAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "stage",
        "is_active",
        "created_at",
    )

    list_filter = (
        "stage",
        "is_active",
    )

    search_fields = (
        "name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "grade_level",
        "academic_year",
        "is_active",
    )

    list_filter = (
        "academic_year",
        "grade_level__stage",
        "grade_level",
        "is_active",
    )

    search_fields = (
        "name",
        "grade_level__name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "academic_year",
        "grade_level",
    )


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "is_active",
        "created_at",
    )

    list_filter = (
        "is_active",
    )

    search_fields = (
        "name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(GradeSubject)
class GradeSubjectAdmin(admin.ModelAdmin):
    list_display = (
        "subject",
        "grade_level",
        "academic_year",
        "is_active",
    )

    list_filter = (
        "academic_year",
        "grade_level__stage",
        "grade_level",
        "subject",
        "is_active",
    )

    search_fields = (
        "subject__name",
        "grade_level__name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "academic_year",
        "grade_level",
        "subject",
    )
