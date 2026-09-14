from django.contrib.auth.models import Permission
from rest_framework import serializers

from accounts.permission_catalog import ALL_MANAGEABLE_PERMISSIONS


class StrictPermissionCodeField(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class PermissionCodeSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()


class PermissionModuleSerializer(serializers.Serializer):
    module = serializers.CharField()
    label = serializers.CharField()
    permissions = PermissionCodeSerializer(many=True)


class PermissionCatalogSerializer(serializers.Serializer):
    modules = PermissionModuleSerializer(many=True)


class PermissionUserSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    username = serializers.CharField(read_only=True)
    full_name = serializers.SerializerMethodField()
    role = serializers.CharField(read_only=True)
    role_display = serializers.CharField(source="get_role_display", read_only=True)

    def get_full_name(self, user):
        return user.get_full_name().strip() or user.username


class UserPermissionsResponseSerializer(serializers.Serializer):
    user = PermissionUserSerializer()
    permissions = serializers.ListField(child=serializers.CharField())


class UserPermissionsReplaceSerializer(serializers.Serializer):
    permissions = serializers.ListField(
        child=StrictPermissionCodeField(trim_whitespace=False),
        allow_empty=True,
    )

    def validate_permissions(self, permission_codes):
        if len(permission_codes) != len(set(permission_codes)):
            raise serializers.ValidationError(
                "لا يجوز تكرار رمز الصلاحية في القائمة."
            )

        invalid_codes = [
            code
            for code in permission_codes
            if code not in ALL_MANAGEABLE_PERMISSIONS
        ]
        if invalid_codes:
            raise serializers.ValidationError(
                f"صلاحيات غير معتمدة: {', '.join(sorted(invalid_codes))}."
            )

        query = Permission.objects.none()
        for code in permission_codes:
            app_label, codename = code.split(".", 1)
            query = query | Permission.objects.filter(
                content_type__app_label=app_label,
                codename=codename,
            )

        permissions = list(query.select_related("content_type"))
        resolved_codes = {
            f"{permission.content_type.app_label}.{permission.codename}"
            for permission in permissions
        }
        unresolved_codes = set(permission_codes) - resolved_codes
        if unresolved_codes:
            raise serializers.ValidationError(
                "تعذر ربط الصلاحيات التالية بالنظام: "
                f"{', '.join(sorted(unresolved_codes))}."
            )

        self.permission_objects = permissions
        return permission_codes
