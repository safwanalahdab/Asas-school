from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.mobile_authentication import MobileJWTAuthentication
from accounts.mobile_permissions import IsMobileGuardian
from config.api_responses import ArabicApiResponseMixin

from .mobile_selectors import (
    get_guardian_child_or_404,
    get_guardian_children_queryset,
)
from .mobile_serializers import (
    MobileChildDetailResponseSerializer,
    MobileChildSerializer,
    MobileChildrenErrorResponseSerializer,
    MobileChildrenListResponseSerializer,
)


class MobileChildrenListView(
    ArabicApiResponseMixin,
    APIView,
):
    """
    يرجع قائمة أبناء ولي الأمر الحالي فقط.
    """

    authentication_classes = [
        MobileJWTAuthentication,
    ]

    permission_classes = [
        IsAuthenticated,
        IsMobileGuardian,
    ]

    @extend_schema(
        responses={
            200: MobileChildrenListResponseSerializer,
            401: MobileChildrenErrorResponseSerializer,
            403: MobileChildrenErrorResponseSerializer,
        },
        description=(
            "جلب قائمة الطلاب الفعالين المرتبطين "
            "بولـي الأمر الحالي بعلاقة فعالة."
        ),
    )
    def get(self, request):
        children = get_guardian_children_queryset(
            guardian=request.user,
        )

        serializer = MobileChildSerializer(
            children,
            many=True,
        )

        return Response(
            {
                "code": "MOBILE_CHILDREN_RETRIEVED",
                "detail": "تم جلب قائمة الأبناء بنجاح.",
                "data": serializer.data,
            }
        )


class MobileChildDetailView(
    ArabicApiResponseMixin,
    APIView,
):
    """
    يرجع تفاصيل ابن واحد فقط إذا كان تابعًا
    لولي الأمر الحالي.
    """

    authentication_classes = [
        MobileJWTAuthentication,
    ]

    permission_classes = [
        IsAuthenticated,
        IsMobileGuardian,
    ]

    @extend_schema(
        responses={
            200: MobileChildDetailResponseSerializer,
            401: MobileChildrenErrorResponseSerializer,
            403: MobileChildrenErrorResponseSerializer,
            404: MobileChildrenErrorResponseSerializer,
        },
        description=(
            "جلب تفاصيل طالب واحد بشرط أن يكون "
            "فعالًا ومرتبطًا بولي الأمر الحالي "
            "بعلاقة GuardianStudent فعالة."
        ),
    )
    def get(
        self,
        request,
        student_id,
    ):
        student = get_guardian_child_or_404(
            guardian=request.user,
            student_id=student_id,
        )

        serializer = MobileChildSerializer(
            student,
        )

        return Response(
            {
                "code": "MOBILE_CHILD_RETRIEVED",
                "detail": "تم جلب بيانات الطالب بنجاح.",
                "data": serializer.data,
            }
        )