from rest_framework.permissions import BasePermission

from accounts.policies import (
    can_access_web_dashboard,
    can_create_accounts,
    can_view_accounts,
)

class IsWebDashboardUser(BasePermission):
    """
    تسمح فقط لمستخدمي لوحة الويب.

    تتحقق من:
    1. المستخدم مسجل دخول.
    2. دوره مسموح في لوحة الويب.
    3. الـJWT صدر من Web Login.
    """

    message = {
        "code": "WEB_DASHBOARD_ACCESS_DENIED",
        "detail": "هذا الحساب غير مخول لاستخدام لوحة الإدارة.",
    }

    def has_permission(self, request, view):
        if not can_access_web_dashboard(request.user):
            return False

        if (
            request.user.must_change_password
            and not getattr(view, "allow_password_change_required", False)
        ):
            self.message = {
                "code": "PASSWORD_CHANGE_REQUIRED",
                "detail": "يجب تغيير كلمة المرور أولاً.",
            }
            return False

        token = request.auth

        if token is None:
            return False

        return token.get("client") == "web"


class PasswordChangeGate(BasePermission):
    message = {"code": "PASSWORD_CHANGE_REQUIRED", "detail": "يجب تغيير كلمة المرور أولاً."}

    def has_permission(self, request, view):
        user = request.user
        return not (
            user and user.is_authenticated and user.must_change_password
            and not getattr(view, "allow_password_change_required", False)
        )


class CanCreateAccounts(BasePermission):
    message = {
        "code": "ACCOUNT_CREATION_FORBIDDEN",
        "detail": "ليس لديك صلاحية لإنشاء الحسابات.",
    }

    def has_permission(self, request, view):
        return can_create_accounts(request.user)


class CanResetPasswords(BasePermission):
    message = {
        "code": "PASSWORD_RESET_FORBIDDEN",
        "detail": "ليس لديك صلاحية لإعادة تعيين كلمات المرور.",
    }

    def has_permission(self, request, view):
        user = request.user
        return bool(user.is_superuser or user.role == user.Role.SCHOOL_ADMIN)

class CanViewAccounts(BasePermission):
    """
    تتحقق من أن المستخدم يملك صلاحية
    فتح قائمة حسابات المستخدمين.
    """

    message = {
        "code": "ACCOUNT_LIST_FORBIDDEN",
        "detail": "ليس لديك صلاحية لعرض حسابات المستخدمين.",
    }

    def has_permission(self, request, view):
        return can_view_accounts(request.user)