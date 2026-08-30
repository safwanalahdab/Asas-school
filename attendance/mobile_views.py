from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.mobile_authentication import MobileJWTAuthentication
from accounts.mobile_permissions import IsMobileGuardian
from config.api_responses import ArabicApiResponseMixin
from students.mobile_selectors import get_guardian_child_or_404

from .mobile_selectors import (
    get_mobile_attendance_queryset,
    get_mobile_attendance_summary,
    get_mobile_today_attendance,
)
from .mobile_serializers import (
    MobileAttendanceErrorSerializer,
    MobileAttendanceHistoryDataSerializer,
    MobileAttendanceHistoryResponseSerializer,
    MobileAttendanceQuerySerializer,
    MobileTodayAttendanceDataSerializer,
    MobileTodayAttendanceResponseSerializer,
)
from .models import AttendanceRecord


class MobileAttendancePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50


def _student_data(student):
    return {"id": student.id, "full_name": student.full_name}


def _academic_year_data(enrollment):
    if enrollment is None:
        return None
    return {"id": enrollment.academic_year_id, "name": enrollment.academic_year.name}


class MobileChildTodayAttendanceView(ArabicApiResponseMixin, APIView):
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [IsAuthenticated, IsMobileGuardian]

    @extend_schema(
        parameters=[OpenApiParameter(
            "student_id", type={"type": "string", "format": "uuid"},
            location=OpenApiParameter.PATH,
        )],
        responses={
            200: MobileTodayAttendanceResponseSerializer,
            401: MobileAttendanceErrorSerializer,
            403: MobileAttendanceErrorSerializer,
            404: MobileAttendanceErrorSerializer,
        },
        description="واجهة قراءة فقط تعرض حضور الطالب لليوم الحالي.",
    )
    def get(self, request, student_id):
        student = get_guardian_child_or_404(
            guardian=request.user, student_id=student_id
        )
        today = timezone.localdate()
        enrollments = getattr(student, "mobile_current_enrollments", [])
        enrollment = enrollments[0] if enrollments else None
        record = None
        if enrollment is not None:
            record = get_mobile_today_attendance(
                enrollment=enrollment, attendance_date=today
            )
        if record is None or record.status == AttendanceRecord.Status.UNMARKED:
            record = None
            is_recorded = False
            status = None
            status_display = "لم يتم تسجيل الحضور بعد"
        else:
            is_recorded = True
            status = record.status
            status_display = record.get_status_display()

        data = MobileTodayAttendanceDataSerializer({
            "student": _student_data(student),
            "academic_year": _academic_year_data(enrollment),
            "date": today,
            "is_recorded": is_recorded,
            "status": status,
            "status_display": status_display,
            "record": record,
        }).data
        return Response({
            "code": "MOBILE_CHILD_ATTENDANCE_RETRIEVED",
            "detail": "تم جلب حضور الطالب لليوم بنجاح.",
            "data": data,
        })


class MobileChildAttendanceHistoryView(ArabicApiResponseMixin, APIView):
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [IsAuthenticated, IsMobileGuardian]

    @extend_schema(
        parameters=[
            OpenApiParameter("student_id", type={"type": "string", "format": "uuid"}, location=OpenApiParameter.PATH),
            OpenApiParameter("date_from", type={"type": "string", "format": "date"}, location=OpenApiParameter.QUERY),
            OpenApiParameter("date_to", type={"type": "string", "format": "date"}, location=OpenApiParameter.QUERY),
            OpenApiParameter("status", type={"type": "string", "enum": ["present", "absent"]}, location=OpenApiParameter.QUERY),
            OpenApiParameter("page", type=int, location=OpenApiParameter.QUERY),
            OpenApiParameter("page_size", type=int, location=OpenApiParameter.QUERY),
        ],
        responses={
            200: MobileAttendanceHistoryResponseSerializer,
            400: MobileAttendanceErrorSerializer,
            401: MobileAttendanceErrorSerializer,
            403: MobileAttendanceErrorSerializer,
            404: MobileAttendanceErrorSerializer,
        },
        description=(
            "واجهة قراءة فقط تعرض سجل حضور الطالب في السنة الحالية. "
            "الحالات غير المحددة لا تظهر في السجل."
        ),
    )
    def get(self, request, student_id):
        student = get_guardian_child_or_404(
            guardian=request.user, student_id=student_id
        )
        query = MobileAttendanceQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        enrollments = getattr(student, "mobile_current_enrollments", [])
        enrollment = enrollments[0] if enrollments else None

        if enrollment is None:
            queryset = AttendanceRecord.objects.none()
            counts = {
                "total_recorded_days": 0, "present_count": 0, "absent_count": 0,
                "excused_absence_count": 0, "unexcused_absence_count": 0,
            }
        else:
            queryset = get_mobile_attendance_queryset(
                enrollment=enrollment,
                date_from=filters.get("date_from"),
                date_to=filters.get("date_to"),
            )
            counts = get_mobile_attendance_summary(queryset=queryset)

        total = counts["total_recorded_days"]
        rate = Decimal("0.00")
        if total:
            rate = (
                Decimal(counts["present_count"]) / Decimal(total) * Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        summary = {**counts, "attendance_rate_percentage": rate}

        records_queryset = queryset
        if filters.get("status"):
            records_queryset = records_queryset.filter(status=filters["status"])
        paginator = MobileAttendancePagination()
        records = paginator.paginate_queryset(records_queryset, request, view=self)
        data = MobileAttendanceHistoryDataSerializer({
            "student": _student_data(student),
            "academic_year": _academic_year_data(enrollment),
            "summary": summary,
            "records": records,
            "pagination": {
                "page": paginator.page.number,
                "page_size": paginator.get_page_size(request),
                "total_pages": paginator.page.paginator.num_pages,
                "total_items": paginator.page.paginator.count,
            },
        }).data
        return Response({
            "code": "MOBILE_CHILD_ATTENDANCE_HISTORY_RETRIEVED",
            "detail": "تم جلب سجل حضور الطالب بنجاح.",
            "data": data,
        })
