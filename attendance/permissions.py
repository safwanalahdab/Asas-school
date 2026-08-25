from rest_framework.permissions import BasePermission
from accounts.models import User

READ_ROLES = {User.Role.SUPERVISOR, User.Role.SCHOOL_ADMIN}


class AttendanceSheetPermission(BasePermission):
    message = {"code": "ATTENDANCE_ACCESS_DENIED", "detail": "ليس لديك صلاحية للوصول إلى وحدة الحضور."}
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if view.action in {"list", "retrieve", "roster"}:
            return user.role in READ_ROLES
        if view.action in {"create", "bulk_update", "normal_departure"}:
            return user.role in READ_ROLES
        return False


class AttendanceRecordPermission(BasePermission):
    message = {"code": "ATTENDANCE_ACCESS_DENIED", "detail": "ليس لديك صلاحية للوصول إلى وحدة الحضور."}
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if view.action in {"list", "retrieve"}:
            return user.role in READ_ROLES
        if view.action == "partial_update":
            return user.role in READ_ROLES
        return False
