from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated

from accounts.permissions import IsWebDashboardUser
from config.api_responses import ArabicApiResponseMixin

from .filters import AuditLogFilter
from .models import AuditLog
from .permissions import CanViewAuditLogs
from .serializers import AuditLogSerializer


@extend_schema_view(
    list=extend_schema(responses=AuditLogSerializer(many=True)),
    retrieve=extend_schema(responses=AuditLogSerializer),
)
class AuditLogViewSet(
    ArabicApiResponseMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = AuditLog.objects.select_related("actor").all()
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated, IsWebDashboardUser, CanViewAuditLogs]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = AuditLogFilter
    search_fields = ["actor_display", "message", "target_display"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]
    http_method_names = ["get", "head", "options"]
    response_messages = {
        "list": ("AUDIT_LOGS_RETRIEVED", "تم جلب سجل النشاطات بنجاح."),
        "retrieve": ("AUDIT_LOG_RETRIEVED", "تم جلب تفاصيل سجل النشاط بنجاح."),
    }
