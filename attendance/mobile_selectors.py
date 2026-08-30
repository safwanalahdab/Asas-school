from django.db.models import Count, Q

from .models import AttendanceRecord


def get_mobile_today_attendance(*, enrollment, attendance_date):
    return AttendanceRecord.objects.filter(
        enrollment=enrollment, sheet__attendance_date=attendance_date,
    ).select_related("sheet").first()


def get_mobile_attendance_queryset(*, enrollment, date_from=None, date_to=None):
    queryset = AttendanceRecord.objects.filter(
        enrollment=enrollment,
        status__in=(AttendanceRecord.Status.PRESENT, AttendanceRecord.Status.ABSENT),
    ).select_related("sheet")
    if date_from is not None:
        queryset = queryset.filter(sheet__attendance_date__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(sheet__attendance_date__lte=date_to)
    return queryset.order_by("-sheet__attendance_date", "-created_at")


def get_mobile_attendance_summary(*, queryset):
    return queryset.order_by().aggregate(
        total_recorded_days=Count("id"),
        present_count=Count("id", filter=Q(status=AttendanceRecord.Status.PRESENT)),
        absent_count=Count("id", filter=Q(status=AttendanceRecord.Status.ABSENT)),
        excused_absence_count=Count("id", filter=Q(
            status=AttendanceRecord.Status.ABSENT,
            absence_type=AttendanceRecord.AbsenceType.EXCUSED,
        )),
        unexcused_absence_count=Count("id", filter=Q(
            status=AttendanceRecord.Status.ABSENT,
            absence_type=AttendanceRecord.AbsenceType.UNEXCUSED,
        )),
    )
