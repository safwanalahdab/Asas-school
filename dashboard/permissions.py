from django.contrib.auth import get_user_model

from rest_framework.permissions import BasePermission


User = get_user_model()


class CanViewDashboardOverview(BasePermission):
    message = {
        "code": "DASHBOARD_ACCESS_DENIED",
        "detail": "ليس لديك صلاحية للوصول إلى إحصائيات لوحة التحكم.",
    }

    def has_permission(
        self,
        request,
        view,
    ):
        user = request.user

        if (
            not user
            or not user.is_authenticated
        ):
            return False

        if user.is_superuser:
            return True

        return (
            user.role
            == User.Role.SCHOOL_ADMIN
        )