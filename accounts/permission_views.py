from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permission_catalog import (
    catalog_modules,
    direct_business_permission_codes,
)
from accounts.permission_serializers import (
    PermissionCatalogSerializer,
    PermissionUserSerializer,
    UserPermissionsReplaceSerializer,
    UserPermissionsResponseSerializer,
)
from accounts.permissions import CanManageUserPermissions
from accounts.services import replace_user_business_permissions
from audit_logs.services import get_request_ip
from config.api_responses import ArabicApiResponseMixin


User = get_user_model()


class PermissionCatalogView(ArabicApiResponseMixin, APIView):
    permission_classes = [IsAuthenticated, CanManageUserPermissions]

    @extend_schema(responses={status.HTTP_200_OK: PermissionCatalogSerializer})
    def get(self, request):
        return Response(
            {
                "code": "PERMISSION_CATALOG_RETRIEVED",
                "detail": "تم جلب قائمة صلاحيات الأعمال بنجاح.",
                "modules": catalog_modules(),
            }
        )


class UserPermissionsView(ArabicApiResponseMixin, APIView):
    permission_classes = [IsAuthenticated, CanManageUserPermissions]

    def get_target(self, user_id):
        target = get_object_or_404(User, pk=user_id)
        if target.is_superuser:
            raise PermissionDenied(
                {
                    "code": "SUPERUSER_PERMISSION_MANAGEMENT_FORBIDDEN",
                    "detail": "لا يمكن إدارة صلاحيات المدير العام المباشرة.",
                }
            )
        return target

    def response_data(self, target):
        return {
            "user": PermissionUserSerializer(target).data,
            "permissions": direct_business_permission_codes(target),
        }

    @extend_schema(responses={status.HTTP_200_OK: UserPermissionsResponseSerializer})
    def get(self, request, user_id):
        target = self.get_target(user_id)
        return Response(
            {
                "code": "USER_PERMISSIONS_RETRIEVED",
                "detail": "تم جلب صلاحيات المستخدم بنجاح.",
                **self.response_data(target),
            }
        )

    @extend_schema(
        request=UserPermissionsReplaceSerializer,
        responses={status.HTTP_200_OK: UserPermissionsResponseSerializer},
    )
    def put(self, request, user_id):
        serializer = UserPermissionsReplaceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target, changed = replace_user_business_permissions(
            target_user_id=user_id,
            permission_codes=serializer.validated_data["permissions"],
            permission_objects=serializer.permission_objects,
            actor=request.user,
            ip_address=get_request_ip(request),
        )
        return Response(
            {
                "code": (
                    "USER_PERMISSIONS_UPDATED"
                    if changed
                    else "USER_PERMISSIONS_UNCHANGED"
                ),
                "detail": (
                    "تم تحديث صلاحيات المستخدم بنجاح."
                    if changed
                    else "صلاحيات المستخدم مطابقة للقائمة المطلوبة مسبقاً."
                ),
                **self.response_data(target),
            }
        )
