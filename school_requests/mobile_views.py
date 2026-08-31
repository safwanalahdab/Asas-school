from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.mixins import CreateModelMixin, ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import GenericViewSet

from accounts.mobile_authentication import MobileJWTAuthentication
from accounts.mobile_permissions import IsMobileGuardian
from config.api_responses import ArabicApiResponseMixin

from .mobile_serializers import MobileSchoolRequestSerializer
from .mobile_throttles import (
    MobileSchoolRequestBurstThrottle,
    MobileSchoolRequestHourlyThrottle,
)
from .models import SchoolRequest


@extend_schema_view(
    list=extend_schema(
        description="يعرض طلبات ولي الأمر المصادق عليه فقط.",
        responses={200: MobileSchoolRequestSerializer(many=True)},
    ),
    create=extend_schema(
        description=(
            "ينشئ شكوى أو استفسارًا أو اقتراحًا. الحقول guardian وstatus "
            "وschool_response وhandled_by وanswered_at يتحكم بها الخادم فقط."
        ),
        request=MobileSchoolRequestSerializer,
        responses={201: MobileSchoolRequestSerializer},
    ),
    retrieve=extend_schema(
        description="يعرض طلبًا واحدًا مملوكًا لولي الأمر المصادق عليه.",
        responses={200: MobileSchoolRequestSerializer},
    ),
)
class MobileSchoolRequestViewSet(
    ArabicApiResponseMixin,
    CreateModelMixin,
    ListModelMixin,
    RetrieveModelMixin,
    GenericViewSet,
):
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [IsAuthenticated, IsMobileGuardian]
    serializer_class = MobileSchoolRequestSerializer
    http_method_names = ["get", "post", "head", "options"]

    response_messages = {
        "list": ("MOBILE_SCHOOL_REQUESTS_RETRIEVED", "تم جلب الطلبات بنجاح."),
        "retrieve": ("MOBILE_SCHOOL_REQUEST_RETRIEVED", "تم جلب الطلب بنجاح."),
        "create": ("MOBILE_SCHOOL_REQUEST_CREATED", "تم إرسال الطلب بنجاح."),
    }

    def get_queryset(self):
        return SchoolRequest.objects.filter(
            guardian=self.request.user,
        ).select_related("student")

    def get_throttles(self):
        if self.action == "create":
            return [
                MobileSchoolRequestBurstThrottle(),
                MobileSchoolRequestHourlyThrottle(),
            ]
        return []

    def perform_create(self, serializer):
        serializer.save(
            guardian=self.request.user,
            status=SchoolRequest.Status.NEW,
            school_response="",
            handled_by=None,
            answered_at=None,
        )
