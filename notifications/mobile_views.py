from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from rest_framework.views import APIView

from accounts.mobile_authentication import MobileJWTAuthentication
from accounts.mobile_permissions import IsMobileGuardian
from config.api_responses import ArabicApiResponseMixin

from .mobile_filters import MobileNotificationFilter
from .mobile_pagination import MobileNotificationPagination
from .mobile_serializers import (
    MobileNotificationSerializer,
    MobilePushDeviceRegistrationSerializer,
    MobilePushDeviceSerializer,
    MobilePushDeviceUnregisterSerializer,
)
from .models import Notification
from .device_services import register_push_device, unregister_push_device
from .throttles import (
    MobileDeviceRegistrationThrottle,
    MobileDeviceUnregistrationThrottle,
)
from .services import mark_all_notifications_as_read, mark_notification_as_read


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                "is_read", str, enum=["true", "false"],
                description="تصفية الإشعارات حسب حالة القراءة.",
            ),
            OpenApiParameter("page", int, description="رقم الصفحة."),
            OpenApiParameter(
                "page_size", int, description="حجم الصفحة، بحد أقصى 100."
            ),
        ],
        responses={200: MobileNotificationSerializer(many=True)},
    ),
    retrieve=extend_schema(responses={200: MobileNotificationSerializer}),
)
class MobileNotificationViewSet(
    ArabicApiResponseMixin,
    ListModelMixin,
    RetrieveModelMixin,
    GenericViewSet,
):
    queryset = Notification.objects.none()
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [IsAuthenticated, IsMobileGuardian]
    serializer_class = MobileNotificationSerializer
    pagination_class = MobileNotificationPagination
    filter_backends = [MobileNotificationFilter]
    http_method_names = ["get", "post", "head", "options"]
    lookup_url_kwarg = "notification_id"

    response_messages = {
        "list": (
            "MOBILE_NOTIFICATIONS_RETRIEVED",
            "تم جلب الإشعارات بنجاح.",
        ),
        "retrieve": (
            "MOBILE_NOTIFICATION_RETRIEVED",
            "تم جلب الإشعار بنجاح.",
        ),
        "read": (
            "MOBILE_NOTIFICATION_READ",
            "تم تعليم الإشعار كمقروء.",
        ),
        "read_all": (
            "MOBILE_NOTIFICATIONS_READ_ALL",
            "تم تعليم جميع الإشعارات كمقروءة.",
        ),
        "unread_count": (
            "MOBILE_NOTIFICATION_UNREAD_COUNT_RETRIEVED",
            "تم جلب عدد الإشعارات غير المقروءة بنجاح.",
        ),
    }

    def get_queryset(self):
        return Notification.objects.filter(
            recipient=self.request.user,
        ).select_related("student")

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        unread_count = Notification.objects.filter(
            recipient=request.user,
            is_read=False,
        ).count()
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response = self.get_paginated_response(serializer.data)
        response.data["meta"] = {
            "unread_count": unread_count,
            "page": self.paginator.page.number,
            "page_size": self.paginator.get_page_size(request),
            "count": self.paginator.page.paginator.count,
        }
        return response

    @extend_schema(request=None, responses={200: MobileNotificationSerializer})
    @action(detail=True, methods=["post"], url_path="read")
    def read(self, request, notification_id=None):
        notification = self.get_object()
        mark_notification_as_read(notification)
        return Response(self.get_serializer(notification).data)

    @extend_schema(request=None, responses={200: dict})
    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        updated_count = mark_all_notifications_as_read(recipient=request.user)
        return Response({"updated_count": updated_count})

    @extend_schema(responses={200: dict})
    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        count = Notification.objects.filter(
            recipient=request.user,
            is_read=False,
        ).count()
        return Response({"unread_count": count})


class MobilePushDeviceRegistrationView(ArabicApiResponseMixin, APIView):
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [IsAuthenticated, IsMobileGuardian]
    throttle_classes = [MobileDeviceRegistrationThrottle]
    response_messages = {
        "post": (
            "MOBILE_DEVICE_REGISTERED",
            "تم تسجيل الجهاز بنجاح.",
        )
    }

    @extend_schema(
        request=MobilePushDeviceRegistrationSerializer,
        responses={
            200: MobilePushDeviceSerializer,
            400: dict,
            401: dict,
            403: dict,
            429: dict,
        },
    )
    def post(self, request):
        serializer = MobilePushDeviceRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device, _created = register_push_device(
            user=request.user,
            **serializer.validated_data,
        )
        return Response(MobilePushDeviceSerializer(device).data)


class MobilePushDeviceUnregisterView(ArabicApiResponseMixin, APIView):
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [IsAuthenticated, IsMobileGuardian]
    throttle_classes = [MobileDeviceUnregistrationThrottle]
    response_messages = {
        "post": (
            "MOBILE_DEVICE_UNREGISTERED",
            "تم إلغاء تسجيل الجهاز بنجاح.",
        )
    }

    @extend_schema(
        request=MobilePushDeviceUnregisterSerializer,
        responses={200: dict, 400: dict, 401: dict, 403: dict, 429: dict},
    )
    def post(self, request):
        serializer = MobilePushDeviceUnregisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        unregister_push_device(user=request.user, **serializer.validated_data)
        return Response({"unregistered": True})
