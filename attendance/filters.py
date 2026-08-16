from django_filters import rest_framework as filters
from .models import AttendanceRecord, AttendanceSheet


class AttendanceSheetFilter(filters.FilterSet):
    grade_level = filters.UUIDFilter(field_name="section__grade_level_id")
    academic_year = filters.UUIDFilter(field_name="section__academic_year_id")
    class Meta:
        model = AttendanceSheet
        fields = ("attendance_date", "section", "grade_level", "academic_year", "created_by")


class AttendanceRecordFilter(filters.FilterSet):
    section = filters.UUIDFilter(field_name="sheet__section_id")
    attendance_date = filters.DateFilter(field_name="sheet__attendance_date")
    student = filters.UUIDFilter(field_name="enrollment__student_id")
    class Meta:
        model = AttendanceRecord
        fields = ("sheet", "status", "absence_type", "section", "attendance_date", "student")
