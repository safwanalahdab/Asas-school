from django.contrib.auth import get_user_model

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.mixins import (
    CreateModelMixin,
    ListModelMixin,
    RetrieveModelMixin,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from accounts.permissions import PasswordChangeGate
from config.api_responses import ArabicApiResponseMixin

from .filters import AppointmentRequestFilter
from .models import AppointmentRequest
from .permissions import CanAccessAppointments
from .serializers import (
    AppointmentDecisionSerializer,
    AppointmentRequestSerializer,
)
from .services import (
    approve_appointment_request,
    reject_appointment_request,
)


User = get_user_model()


class AppointmentRequestViewSet(
    ArabicApiResponseMixin,
    CreateModelMixin,
    ListModelMixin,
    RetrieveModelMixin,
    GenericViewSet,
):
    queryset = (
        AppointmentRequest.objects
        .select_related(
            "guardian",
            "decided_by",
        )
    )

    permission_classes = [
        IsAuthenticated,
        PasswordChangeGate,
        CanAccessAppointments,
    ]

    filterset_class = AppointmentRequestFilter

    ordering_fields = [
        "requested_date",
        "created_at",
    ]

    ordering = [
        "-created_at",
    ]

    http_method_names = [
        "get",
        "post",
        "head",
        "options",
    ]

    response_messages = {
        "list": (
            "APPOINTMENT_REQUESTS_RETRIEVED",
            "تم جلب طلبات المواعيد بنجاح.",
        ),
        "retrieve": (
            "APPOINTMENT_REQUEST_RETRIEVED",
            "تم جلب طلب الموعد بنجاح.",
        ),
        "create": (
            "APPOINTMENT_REQUEST_CREATED",
            "تم إرسال طلب الموعد بنجاح.",
        ),
        "approve": (
            "APPOINTMENT_REQUEST_APPROVED",
            "تم قبول طلب الموعد بنجاح.",
        ),
        "reject": (
            "APPOINTMENT_REQUEST_REJECTED",
            "تم رفض طلب الموعد بنجاح.",
        ),
    }

    def get_serializer_class(self):
        if self.action in {
            "approve",
            "reject",
        }:
            return AppointmentDecisionSerializer

        return AppointmentRequestSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if user.is_superuser:
            return queryset

        if user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SECRETARIAT,
        }:
            return queryset

        if user.role == User.Role.GUARDIAN:
            return queryset.filter(
                guardian=user,
            )

        return queryset.none()

    def perform_create(
        self,
        serializer,
    ):
        serializer.save(
            guardian=self.request.user,
            status=AppointmentRequest.Status.PENDING,
        )

    @extend_schema(
        request=AppointmentDecisionSerializer,
        responses=AppointmentRequestSerializer,
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="approve",
    )
    def approve(
        self,
        request,
        pk=None,
    ):
        appointment = self.get_object()

        serializer = self.get_serializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        appointment = approve_appointment_request(
            appointment=appointment,
            actor=request.user,
            decision_reason=serializer.validated_data[
                "decision_reason"
            ],
        )

        response_serializer = AppointmentRequestSerializer(
            appointment,
            context=self.get_serializer_context(),
        )

        return Response(
            response_serializer.data,
        )

    @extend_schema(
        request=AppointmentDecisionSerializer,
        responses=AppointmentRequestSerializer,
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="reject",
    )
    def reject(
        self,
        request,
        pk=None,
    ):
        appointment = self.get_object()

        serializer = self.get_serializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        appointment = reject_appointment_request(
            appointment=appointment,
            actor=request.user,
            decision_reason=serializer.validated_data[
                "decision_reason"
            ],
        )

        response_serializer = AppointmentRequestSerializer(
            appointment,
            context=self.get_serializer_context(),
        )

        return Response(
            response_serializer.data,
        )