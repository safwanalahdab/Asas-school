from rest_framework.permissions import BasePermission
from accounts.models import User

ATTENDANCE_ROLES = {User.Role.TEACHER, User.Role.SUPERVISOR, User.Role.SCHOOL_ADMIN}
ADMIN_ROLES = {User.Role.SUPERVISOR, User.Role.SCHOOL_ADMIN}


class AttendanceSheetPermission(BasePermission):
    message = {"code": "ATTENDANCE_ACCESS_DENIED", "detail": "ليس لديك صلاحية للوصول إلى وحدة الحضور."}
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if user.role not in ATTENDANCE_ROLES:
            return False
        if view.action in {"bulk_update", "normal_departure"}:
            return user.role in ADMIN_ROLES
        return view.action in {"list", "retrieve", "create"}


class AttendanceRecordPermission(BasePermission):
    message = {"code": "ATTENDANCE_ACCESS_DENIED", "detail": "ليس لديك صلاحية للوصول إلى وحدة الحضور."}
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if user.role not in ATTENDANCE_ROLES:
            return False
        if view.action == "partial_update":
            return user.role in ADMIN_ROLES
        return view.action in {"list", "retrieve"}
