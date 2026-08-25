from django.contrib.auth import get_user_model
from rest_framework.permissions import BasePermission

User = get_user_model()


class CanViewAuditLogs(BasePermission):
    message = "سجل النشاطات متاح لمدير المدرسة فقط."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated
            and (user.is_superuser or user.role == User.Role.SCHOOL_ADMIN)
        )
