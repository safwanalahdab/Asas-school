from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.mobile_authentication import MobileJWTAuthentication
from accounts.mobile_permissions import IsMobileGuardian
from config.api_responses import ArabicApiResponseMixin
from students.mobile_selectors import get_guardian_child_or_404

from .mobile_serializers import (
    MobileHomeworkErrorSerializer,
    MobileHomeworkFilterSerializer,
    MobileHomeworkResponseSerializer,
    MobileHomeworkSerializer,
)
from .models import Homework


class MobileChildHomeworkView(ArabicApiResponseMixin, APIView):
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [IsAuthenticated, IsMobileGuardian]

    @extend_schema(
        parameters=[
            OpenApiParameter("student_id", type={"type": "string", "format": "uuid"}, location=OpenApiParameter.PATH),
            OpenApiParameter("date_from", type={"type": "string", "format": "date"}, location=OpenApiParameter.QUERY),
            OpenApiParameter("date_to", type={"type": "string", "format": "date"}, location=OpenApiParameter.QUERY),
            OpenApiParameter("subject", type={"type": "string", "format": "uuid"}, location=OpenApiParameter.QUERY),
        ],
        responses={
            200: MobileHomeworkResponseSerializer,
            400: MobileHomeworkErrorSerializer,
            401: MobileHomeworkErrorSerializer,
            403: MobileHomeworkErrorSerializer,
            404: MobileHomeworkErrorSerializer,
        },
    )
    def get(self, request, student_id):
        student = get_guardian_child_or_404(
            guardian=request.user, student_id=student_id
        )
        filters = MobileHomeworkFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)

        enrollments = getattr(student, "mobile_current_enrollments", [])
        if not enrollments:
            homework = Homework.objects.none()
        else:
            enrollment = enrollments[0]
            homework = Homework.objects.filter(
                teacher_assignment__section=enrollment.section,
                teacher_assignment__grade_subject__academic_year=enrollment.academic_year,
            ).select_related(
                "teacher_assignment__teacher",
                "teacher_assignment__section",
                "teacher_assignment__grade_subject__subject",
            )
            values = filters.validated_data
            if "date_from" in values:
                homework = homework.filter(homework_date__gte=values["date_from"])
            if "date_to" in values:
                homework = homework.filter(homework_date__lte=values["date_to"])
            if "subject" in values:
                homework = homework.filter(
                    teacher_assignment__grade_subject__subject_id=values["subject"]
                )
            homework = homework.order_by("-homework_date", "-created_at")

        serializer = MobileHomeworkSerializer(
            homework, many=True, context={"request": request}
        )
        return Response({
            "code": "MOBILE_CHILD_HOMEWORK_RETRIEVED",
            "detail": "تم جلب واجبات الطالب بنجاح.",
            "data": serializer.data,
        })
