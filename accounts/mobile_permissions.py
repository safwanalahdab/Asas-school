from rest_framework.permissions import BasePermission

from accounts.models import User


class IsMobileGuardian(BasePermission):
    """Reusable Guardian-mobile boundary, including the forced-password gate."""

    message = {
        "code": "MOBILE_GUARDIAN_ACCESS_DENIED",
        "detail": "هذا الحساب غير مخول لاستخدام تطبيق ولي الأمر.",
    }

    def has_permission(self, request, view):
        user = request.user
        if not (
            user
            and user.is_authenticated
            and user.is_active
            and user.role == User.Role.GUARDIAN
            and request.auth is not None
            and request.auth.get("client") == "mobile"
        ):
            return False

        if user.must_change_password and not getattr(
            view, "allow_password_change_required", False
        ):
            self.message = {
                "code": "PASSWORD_CHANGE_REQUIRED",
                "detail": "يجب تغيير كلمة المرور أولاً.",
            }
            return False
        return True
