from django.contrib import admin

from .models import AttendanceRecord, AttendanceSheet


@admin.register(AttendanceSheet)
class AttendanceSheetAdmin(admin.ModelAdmin):
    list_display = (
        "section",
        "attendance_date",
        "created_by",
        "created_at",
    )

    list_filter = (
        "attendance_date",
        "section__grade_level",
        "section",
    )

    search_fields = (
        "section__name",
        "created_by__username",
        "created_by__first_name",
        "created_by__last_name",
    )

    list_select_related = (
        "section",
        "section__grade_level",
        "created_by",
    )

    readonly_fields = (
        "id",
        "section",
        "attendance_date",
        "created_by",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = (
        "student_display",
        "attendance_date_display",
        "section_display",
        "status",
        "arrival_time",
        "departure_time",
        "updated_at",
    )

    list_filter = (
        "status",
        "absence_type",
        "sheet__attendance_date",
        "sheet__section",
    )

    search_fields = (
        "enrollment__student__first_name",
        "enrollment__student__last_name",
        "enrollment__student__father_name",
        "enrollment__student__mother_name",
    )

    list_select_related = (
        "sheet",
        "sheet__section",
        "enrollment",
        "enrollment__student",
    )

    readonly_fields = (
        "id",
        "sheet",
        "enrollment",
        "status",
        "arrival_time",
        "arrival_method",
        "departure_time",
        "departure_method",
        "absence_type",
        "absence_reason",
        "absence_reason_source",
        "notes",
        "created_at",
        "updated_at",
    )

    @admin.display(
        description="الطالب",
        ordering="enrollment__student__first_name",
    )
    def student_display(self, obj):
        return obj.enrollment.student.full_name

    @admin.display(
        description="التاريخ",
        ordering="sheet__attendance_date",
    )
    def attendance_date_display(self, obj):
        return obj.sheet.attendance_date

    @admin.display(
        description="الشعبة",
        ordering="sheet__section__name",
    )
    def section_display(self, obj):
        return obj.sheet.section

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
