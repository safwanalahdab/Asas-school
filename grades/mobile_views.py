from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.mobile_authentication import MobileJWTAuthentication
from accounts.mobile_permissions import IsMobileGuardian
from config.api_responses import ArabicApiResponseMixin
from students.mobile_selectors import get_guardian_child_or_404

from .mobile_selectors import get_mobile_grades_data
from .mobile_serializers import (
    MobileGradesErrorSerializer,
    MobileGradesDataSerializer,
    MobileGradesQuerySerializer,
    MobileGradesResponseSerializer,
)


class MobileChildGradesView(ArabicApiResponseMixin, APIView):
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [IsAuthenticated, IsMobileGuardian]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "student_id",
                type={"type": "string", "format": "uuid"},
                location=OpenApiParameter.PATH,
            ),
            OpenApiParameter(
                "term",
                type={"type": "string", "format": "uuid"},
                location=OpenApiParameter.QUERY,
                required=False,
            ),
        ],
        responses={
            200: MobileGradesResponseSerializer,
            400: MobileGradesErrorSerializer,
            401: MobileGradesErrorSerializer,
            403: MobileGradesErrorSerializer,
            404: MobileGradesErrorSerializer,
        },
        description=(
            "يعرض فقط التقييمات المنشورة للشعبة الصحيحة للطالب تاريخيًا. "
            "لا تظهر التقييمات المسودة، والطالب بلا تسجيل حالي يعيد نتيجة فارغة. "
            "يجب أن ينتمي term إلى السنة الدراسية الحالية."
        ),
    )
    def get(self, request, student_id):
        student = get_guardian_child_or_404(
            guardian=request.user,
            student_id=student_id,
        )
        enrollments = getattr(student, "mobile_current_enrollments", [])
        enrollment = enrollments[0] if enrollments else None

        term = None
        if enrollment is not None:
            query = MobileGradesQuerySerializer(
                data=request.query_params,
                context={"academic_year": enrollment.academic_year},
            )
            query.is_valid(raise_exception=True)
            term = query.validated_data.get("term")

        grades_data = get_mobile_grades_data(
            student=student,
            enrollment=enrollment,
            term=term,
        )
        data = MobileGradesDataSerializer(grades_data).data
        return Response({
            "code": "MOBILE_CHILD_GRADES_RETRIEVED",
            "detail": "تم جلب علامات الطالب بنجاح.",
            "data": data,
        })
