from rest_framework.permissions import BasePermission

from accounts.models import User


class AcademicManagementPermission(BasePermission):
    """
    السماح بإدارة البنية الأكاديمية لمستخدمي لوحة التحكم المخولين فقط.
    """

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        return user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SECRETARIAT,
            User.Role.SUPERVISOR,
        }