from django.contrib import admin

from .models import (
    Enrollment,
    GuardianStudent,
    Student,
    StudentAuditLog,
)

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = (
        "full_name_display",
        "gender",
        "birth_date",
        "is_active",
        "created_at",
    )

    list_filter = (
        "gender",
        "is_active",
    )

    search_fields = (
        "first_name",
        "last_name",
        "father_name",
        "mother_name",
    )

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )

    @admin.display(
        description="اسم الطالب",
        ordering="first_name",
    )
    def full_name_display(self, obj):
        return obj.full_name

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(GuardianStudent)
class GuardianStudentAdmin(admin.ModelAdmin):
    list_display = (
        "guardian",
        "student",
        "is_active",
        "created_at",
    )

    list_filter = (
        "is_active",
    )

    search_fields = (
        "guardian__username",
        "guardian__first_name",
        "guardian__last_name",
        "guardian__email",
        "student__first_name",
        "student__last_name",
    )

    list_select_related = (
        "guardian",
        "student",
    )

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "academic_year",
        "grade_level_display",
        "section",
        "enrollment_date",
        "usual_arrival_method",
        "usual_departure_method",
        "created_at",
    )

    list_filter = (
        "academic_year",
        "section__grade_level",
        "section",
        "usual_arrival_method",
        "usual_departure_method",
    )

    search_fields = (
        "student__first_name",
        "student__last_name",
        "student__father_name",
        "student__mother_name",
    )

    list_select_related = (
        "student",
        "academic_year",
        "section",
        "section__grade_level",
    )

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )

    @admin.display(
        description="الصف",
        ordering="section__grade_level__name",
    )
    def grade_level_display(self, obj):
        return obj.section.grade_level.name

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(StudentAuditLog)
class StudentAuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "event_type",
        "student_display",
        "academic_year_display",
        "old_section",
        "new_section",
        "actor",
        "created_at",
    )

    list_filter = (
        "event_type",
        "enrollment__academic_year",
        "old_section",
        "new_section",
    )

    search_fields = (
        "enrollment__student__first_name",
        "enrollment__student__last_name",
        "actor__username",
        "actor__first_name",
        "actor__last_name",
    )

    list_select_related = (
        "actor",
        "enrollment__student",
        "enrollment__academic_year",
        "old_section",
        "new_section",
    )

    readonly_fields = (
        "id",
        "event_type",
        "actor",
        "enrollment",
        "old_section",
        "new_section",
        "created_at",
    )

    @admin.display(
        description="الطالب",
        ordering="enrollment__student__first_name",
    )
    def student_display(self, obj):
        return obj.enrollment.student.full_name

    @admin.display(
        description="السنة الدراسية",
        ordering="enrollment__academic_year__start_date",
    )
    def academic_year_display(self, obj):
        return obj.enrollment.academic_year.name

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False