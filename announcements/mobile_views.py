from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.mobile_authentication import MobileJWTAuthentication
from accounts.mobile_permissions import IsMobileGuardian
from config.api_responses import ArabicApiResponseMixin
from students.mobile_selectors import get_guardian_child_or_404

from .mobile_serializers import (
    MobileAnnouncementSerializer,
    MobileAnnouncementsErrorSerializer,
    MobileAnnouncementsResponseSerializer,
)
from .models import Announcement


class MobileChildAnnouncementsView(ArabicApiResponseMixin, APIView):
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [IsAuthenticated, IsMobileGuardian]

    @extend_schema(
        parameters=[
            OpenApiParameter("student_id", type={"type": "string", "format": "uuid"}, location=OpenApiParameter.PATH),
        ],
        responses={
            200: MobileAnnouncementsResponseSerializer,
            401: MobileAnnouncementsErrorSerializer,
            403: MobileAnnouncementsErrorSerializer,
            404: MobileAnnouncementsErrorSerializer,
        },
    )
    def get(self, request, student_id):
        student = get_guardian_child_or_404(
            guardian=request.user, student_id=student_id
        )
        enrollments = getattr(student, "mobile_current_enrollments", [])
        if not enrollments:
            announcements = Announcement.objects.none()
        else:
            enrollment = enrollments[0]
            today = timezone.localdate()
            target_scope = (
                Q(scope=Announcement.Scope.ALL)
                | Q(
                    scope=Announcement.Scope.GRADES,
                    grade_levels=enrollment.section.grade_level,
                )
                | Q(
                    scope=Announcement.Scope.SECTIONS,
                    sections=enrollment.section,
                )
            )
            announcements = (
                Announcement.objects.filter(
                    target_scope,
                    publish_date__lte=today,
                )
                .filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=today))
                .distinct()
                .order_by("-publish_date", "-created_at")
            )

        serializer = MobileAnnouncementSerializer(
            announcements, many=True, context={"request": request}
        )
        return Response({
            "code": "MOBILE_CHILD_ANNOUNCEMENTS_RETRIEVED",
            "detail": "تم جلب إعلانات الطالب بنجاح.",
            "data": serializer.data,
        })
