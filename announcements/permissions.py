from django.contrib.auth import get_user_model
from rest_framework.permissions import (
    BasePermission,
    SAFE_METHODS,
)


User = get_user_model()


class CanAccessAnnouncements(BasePermission):
    message = "ليس لديك صلاحية للوصول إلى الإعلانات."

    def has_permission(self, request, view):
        user = request.user

        if user.is_superuser:
            return True

        if user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SUPERVISOR,
            User.Role.SECRETARIAT,
        }:
            return True

        if user.role in {
            User.Role.TEACHER,
            User.Role.GUARDIAN,
        }:
            return request.method in SAFE_METHODS

        return False

    def has_object_permission(self, request, view, obj):
        user = request.user

        if user.is_superuser:
            return True

        if user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SUPERVISOR,
            User.Role.SECRETARIAT,
        }:
            return True

        if user.role in {
            User.Role.TEACHER,
            User.Role.GUARDIAN,
        }:
            return request.method in SAFE_METHODS

        return False