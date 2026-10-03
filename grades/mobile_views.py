from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.mobile_authentication import MobileJWTAuthentication
from accounts.mobile_permissions import IsMobileGuardian
from config.api_responses import ArabicApiResponseMixin
from config.pagination import StandardPageNumberPagination
from students.mobile_selectors import get_guardian_child_or_404

from .mobile_selectors import get_mobile_exams, get_mobile_grades_data
from .mobile_serializers import (
    MobileExamSerializer,
    MobileExamsDataSerializer,
    MobileExamsErrorSerializer,
    MobileExamsQuerySerializer,
    MobileExamsResponseSerializer,
    MobileGradesErrorSerializer,
    MobileGradesDataSerializer,
    MobileGradesQuerySerializer,
    MobileGradesResponseSerializer,
)


class MobileExamsPagination(StandardPageNumberPagination):
    max_page_size = 100


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


class MobileChildExamsView(ArabicApiResponseMixin, APIView):
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
                "view",
                type=str,
                enum=["upcoming", "past", "all"],
                default="upcoming",
                location=OpenApiParameter.QUERY,
                description="القادمة تشمل امتحانات اليوم."
            ),
            OpenApiParameter(
                "date_from", type={"type": "string", "format": "date"},
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                "date_to", type={"type": "string", "format": "date"},
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                "term", type={"type": "string", "format": "uuid"},
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                "subject", type={"type": "string", "format": "uuid"},
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                "page", type=int, default=1, location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                "page_size", type=int, default=20,
                location=OpenApiParameter.QUERY,
                description="عدد النتائج في الصفحة، والحد الأعلى 100.",
            ),
        ],
        responses={
            200: MobileExamsResponseSerializer,
            400: MobileExamsErrorSerializer,
            401: MobileExamsErrorSerializer,
            403: MobileExamsErrorSerializer,
            404: MobileExamsErrorSerializer,
        },
        description=(
            "مسار قراءة فقط يعرض مواعيد الامتحانات المنشورة لابن ولي الأمر، "
            "ولا يعرض العلامات أو يعتمد على نشر النتائج. امتحان اليوم ضمن القادمة."
        ),
    )
    def get(self, request, student_id):
        student = get_guardian_child_or_404(
            guardian=request.user,
            student_id=student_id,
        )
        query = MobileExamsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        enrollments = getattr(student, "mobile_current_enrollments", [])
        enrollment = enrollments[0] if enrollments else None
        exams = get_mobile_exams(
            enrollment=enrollment,
            filters=query.validated_data,
        )

        paginator = MobileExamsPagination()
        page = paginator.paginate_queryset(exams, request, view=self)
        serialized_exams = MobileExamSerializer(page, many=True).data
        data = MobileExamsDataSerializer({
            "student": {"id": student.id, "full_name": student.full_name},
            "academic_year": (
                {
                    "id": enrollment.academic_year_id,
                    "name": enrollment.academic_year.name,
                }
                if enrollment is not None
                else None
            ),
            "exams": serialized_exams,
        }).data
        return Response({
            "code": "MOBILE_CHILD_EXAMS_RETRIEVED",
            "detail": "تم جلب مواعيد امتحانات الطالب بنجاح.",
            "data": data,
            "meta": {"pagination": paginator.get_pagination_meta(request)},
        })
