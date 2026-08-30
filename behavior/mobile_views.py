from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.mobile_authentication import MobileJWTAuthentication
from accounts.mobile_permissions import IsMobileGuardian
from config.api_responses import ArabicApiResponseMixin
from students.mobile_selectors import get_guardian_child_or_404

from .mobile_selectors import get_mobile_behavior_notes
from .mobile_serializers import (
    MobileBehaviorDataSerializer,
    MobileBehaviorErrorSerializer,
    MobileBehaviorResponseSerializer,
)
from .models import BehaviorNote


class MobileChildBehaviorView(ArabicApiResponseMixin, APIView):
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [IsAuthenticated, IsMobileGuardian]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "student_id",
                type={"type": "string", "format": "uuid"},
                location=OpenApiParameter.PATH,
            ),
        ],
        responses={
            200: MobileBehaviorResponseSerializer,
            401: MobileBehaviorErrorSerializer,
            403: MobileBehaviorErrorSerializer,
            404: MobileBehaviorErrorSerializer,
        },
        description="واجهة قراءة فقط تعرض ملاحظات سلوك الطالب في السنة الحالية.",
    )
    def get(self, request, student_id):
        student = get_guardian_child_or_404(
            guardian=request.user,
            student_id=student_id,
        )
        enrollments = getattr(student, "mobile_current_enrollments", [])
        enrollment = enrollments[0] if enrollments else None
        notes = get_mobile_behavior_notes(enrollment=enrollment) if enrollment else []

        positive_count = sum(
            note.note_type == BehaviorNote.Type.POSITIVE for note in notes
        )
        negative_count = sum(
            note.note_type == BehaviorNote.Type.NEGATIVE for note in notes
        )
        payload = {
            "student": {"id": student.id, "full_name": student.full_name},
            "academic_year": (
                {
                    "id": enrollment.academic_year_id,
                    "name": enrollment.academic_year.name,
                }
                if enrollment is not None
                else None
            ),
            "summary": {
                "total_notes_count": len(notes),
                "positive_notes_count": positive_count,
                "negative_notes_count": negative_count,
            },
            "notes": notes,
        }
        data = MobileBehaviorDataSerializer(payload).data
        return Response({
            "code": "MOBILE_CHILD_BEHAVIOR_RETRIEVED",
            "detail": "تم جلب الملاحظات السلوكية للطالب بنجاح.",
            "data": data,
        })
