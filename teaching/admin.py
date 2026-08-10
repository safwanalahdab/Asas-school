from django.contrib import admin

from .models import TeacherAssignment


@admin.register(TeacherAssignment)
class TeacherAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "teacher",
        "subject_name",
        "grade_level_name",
        "section",
        "academic_year",
        "start_date",
        "end_date",
    )

    list_filter = (
        "grade_subject__academic_year",
        "grade_subject__grade_level",
        "grade_subject__subject",
        "section",
    )

    search_fields = (
        "teacher__username",
        "teacher__first_name",
        "teacher__last_name",
        "grade_subject__subject__name",
        "grade_subject__grade_level__name",
        "section__name",
    )

    list_select_related = (
        "teacher",
        "grade_subject__subject",
        "grade_subject__grade_level",
        "grade_subject__academic_year",
        "section",
    )

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )

    @admin.display(description="المادة")
    def subject_name(self, obj):
        return obj.grade_subject.subject.name

    @admin.display(description="الصف")
    def grade_level_name(self, obj):
        return obj.grade_subject.grade_level.name

    @admin.display(description="السنة الدراسية")
    def academic_year(self, obj):
        return obj.grade_subject.academic_year.name

    def has_delete_permission(self, request, obj=None):
        return True