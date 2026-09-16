from rest_framework.permissions import BasePermission

from accounts.policies import (
    can_access_web_dashboard,
)
from accounts.permission_catalog import ALL_MANAGEABLE_PERMISSIONS


def has_direct_permission(user, permission_code):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if not user.is_active:
        return False
    if user.is_superuser:
        return True
    if permission_code not in ALL_MANAGEABLE_PERMISSIONS:
        return False

    app_label, codename = permission_code.split(".", 1)
    return user.user_permissions.filter(
        content_type__app_label=app_label,
        codename=codename,
    ).exists()


class ActionBusinessPermission(BasePermission):
    message = {
        "code": "BUSINESS_PERMISSION_DENIED",
        "detail": "ليس لديك صلاحية لتنفيذ هذه العملية.",
    }

    def has_permission(self, request, view):
        # DRF checks permissions before dispatching to http_method_not_allowed.
        # Let dispatch return 405 for methods the view does not support.
        method_name = request.method.lower()
        if method_name not in view.http_method_names:
            return True
        if method_name == "options":
            return True
        action_permissions = getattr(view, "action_permissions", {})
        action_name = getattr(view, "action", None)
        required_permission = action_permissions.get(action_name)
        if required_permission is None:
            method_permissions = getattr(view, "method_permissions", {})
            permission_method = "get" if method_name == "head" else method_name
            if (
                action_name is None
                and method_permissions
                and not hasattr(view, permission_method)
            ):
                return True
            required_permission = method_permissions.get(permission_method)
        return bool(required_permission and has_direct_permission(request.user, required_permission))


class CanManageUserPermissions(BasePermission):
    message = {
        "code": "USER_PERMISSION_MANAGEMENT_FORBIDDEN",
        "detail": "ليس لديك صلاحية لإدارة صلاحيات المستخدمين.",
    }

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated or not user.is_active:
            return False
        if user.is_superuser:
            return True
        return bool(
            user.role == user.Role.SCHOOL_ADMIN
            and has_direct_permission(user, "accounts.manage_user_permissions")
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
