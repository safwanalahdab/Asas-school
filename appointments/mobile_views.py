from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework.mixins import CreateModelMixin, ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import GenericViewSet

from accounts.mobile_authentication import MobileJWTAuthentication
from accounts.mobile_permissions import IsMobileGuardian
from config.api_responses import ArabicApiResponseMixin

from .mobile_filters import MobileAppointmentRequestFilter
from .mobile_serializers import MobileAppointmentRequestSerializer
from .models import AppointmentRequest


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                "status",
                str,
                enum=AppointmentRequest.Status.values,
                description="تصفية حسب حالة الطلب.",
            )
        ],
        responses={200: MobileAppointmentRequestSerializer(many=True)},
    ),
    create=extend_schema(
        request=MobileAppointmentRequestSerializer,
        responses={201: MobileAppointmentRequestSerializer},
    ),
    retrieve=extend_schema(responses={200: MobileAppointmentRequestSerializer}),
)
class MobileAppointmentRequestViewSet(
    ArabicApiResponseMixin,
    CreateModelMixin,
    ListModelMixin,
    RetrieveModelMixin,
    GenericViewSet,
):
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [IsAuthenticated, IsMobileGuardian]
    serializer_class = MobileAppointmentRequestSerializer
    filterset_class = MobileAppointmentRequestFilter
    http_method_names = ["get", "post", "head", "options"]

    response_messages = {
        "list": ("MOBILE_APPOINTMENTS_RETRIEVED", "تم جلب طلبات المواعيد بنجاح."),
        "retrieve": ("MOBILE_APPOINTMENT_RETRIEVED", "تم جلب طلب الموعد بنجاح."),
        "create": ("MOBILE_APPOINTMENT_CREATED", "تم إرسال طلب الموعد بنجاح."),
    }

    def get_queryset(self):
        return AppointmentRequest.objects.filter(guardian=self.request.user)

    def perform_create(self, serializer):
        serializer.save(
            guardian=self.request.user,
            status=AppointmentRequest.Status.PENDING,
            decision_reason="",
            decided_by=None,
            decided_at=None,
        )
