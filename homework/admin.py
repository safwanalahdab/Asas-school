from django.contrib import admin

from .models import Homework


@admin.register(Homework)
class HomeworkAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "teacher",
        "subject",
        "section",
        "homework_date",
        "due_date",
        "created_by",
        "created_at",
    )

    list_filter = (
        "homework_date",
        "due_date",
        "created_at",
    )

    search_fields = (
        "title",
        "description",
        "teacher_assignment__teacher__username",
        "teacher_assignment__grade_subject__subject__name",
        "teacher_assignment__section__name",
    )

    ordering = (
        "-homework_date",
        "-created_at",
    )

    readonly_fields = (
        "created_by",
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "teacher_assignment",
        "teacher_assignment__teacher",
        "teacher_assignment__section",
        "teacher_assignment__grade_subject",
        "teacher_assignment__grade_subject__subject",
        "created_by",
    )

    @admin.display(description="المعلّم")
    def teacher(self, obj):
        return obj.teacher_assignment.teacher

    @admin.display(description="المادة")
    def subject(self, obj):
        return obj.teacher_assignment.grade_subject.subject

    @admin.display(description="الشعبة")
    def section(self, obj):
        return obj.teacher_assignment.section

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user

        super().save_model(
            request,
            obj,
            form,
            change,
        )