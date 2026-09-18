from rest_framework.permissions import BasePermission

from accounts.models import User


class CanViewStudentProfileRole(BasePermission):
    message = {
        "code": "STUDENT_PROFILE_ACCESS_DENIED",
        "detail": "ليس لديك صلاحية للوصول إلى الملف الشامل للطالب.",
    }

    allowed_roles = {
        User.Role.SCHOOL_ADMIN,
        User.Role.SECRETARIAT,
        User.Role.SUPERVISOR,
    }

    def has_permission(self, request, view):
        method_name = request.method.lower()
        if method_name not in view.http_method_names or method_name == "options":
            return True

        user = request.user
        if not user or not user.is_authenticated or not user.is_active:
            return False
        return user.is_superuser or user.role in self.allowed_roles
