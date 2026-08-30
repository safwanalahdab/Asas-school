from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.mobile_authentication import MobileJWTAuthentication
from accounts.mobile_permissions import IsMobileGuardian
from config.api_responses import ArabicApiResponseMixin
from students.mobile_selectors import get_guardian_child_or_404

from .mobile_selectors import get_mobile_finance_data, get_mobile_financial_account
from .mobile_serializers import (
    MobileFinanceDataSerializer,
    MobileFinanceErrorSerializer,
    MobileFinanceResponseSerializer,
)


class MobileChildFinanceView(ArabicApiResponseMixin, APIView):
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [IsAuthenticated, IsMobileGuardian]

    @extend_schema(
        parameters=[OpenApiParameter(
            "student_id", type={"type": "string", "format": "uuid"},
            location=OpenApiParameter.PATH,
        )],
        responses={
            200: MobileFinanceResponseSerializer,
            401: MobileFinanceErrorSerializer,
            403: MobileFinanceErrorSerializer,
            404: MobileFinanceErrorSerializer,
        },
        description=(
            "واجهة قراءة فقط تعرض الوضع المالي للطالب في السنة الحالية. "
            "القيم الإجمالية بالدولار، وتستخدم دفعات الليرة قيمتها التاريخية المخزنة."
        ),
    )
    def get(self, request, student_id):
        student = get_guardian_child_or_404(
            guardian=request.user, student_id=student_id
        )
        enrollments = getattr(student, "mobile_current_enrollments", [])
        enrollment = enrollments[0] if enrollments else None
        account = (
            get_mobile_financial_account(enrollment=enrollment)
            if enrollment is not None else None
        )
        payload = {
            "student": {"id": student.id, "full_name": student.full_name},
            "academic_year": (
                {"id": enrollment.academic_year_id, "name": enrollment.academic_year.name}
                if enrollment is not None else None
            ),
            "account_configured": account is not None,
            "summary": None,
            "discounts": [],
            "payments": [],
        }
        if account is not None:
            payload.update(get_mobile_finance_data(account=account))
        data = MobileFinanceDataSerializer(payload).data
        return Response({
            "code": "MOBILE_CHILD_FINANCE_RETRIEVED",
            "detail": "تم جلب الوضع المالي للطالب بنجاح.",
            "data": data,
        })
