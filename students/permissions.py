from rest_framework.permissions import BasePermission

from accounts.models import User


MANAGEMENT_ROLES = {
    User.Role.SCHOOL_ADMIN,
    User.Role.SECRETARIAT,
    User.Role.SUPERVISOR,
}


class CanRegisterStudent(BasePermission):
    message = {
        "code": "STUDENT_REGISTRATION_FORBIDDEN",
        "detail": "ليس لديك صلاحية لتسجيل الطلاب.",
    }

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (user.is_superuser or user.role in MANAGEMENT_ROLES)
        )


class CanManageStudentHealthProfile(BasePermission):
    message = {
        "code": "STUDENT_HEALTH_PROFILE_FORBIDDEN",
        "detail": "ليس لديك صلاحية لإدارة الملف الصحي للطالب.",
    }

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (user.is_superuser or user.role in MANAGEMENT_ROLES)
        )


class StudentPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        action = getattr(view, "action", None)

        if user.role in MANAGEMENT_ROLES:
            return action in {
                "list",
                "retrieve",
                "create",
                "partial_update",
                "activate",
                "deactivate",
                "destroy",
            }

        if user.role == User.Role.TEACHER:
            return action in {
                "list",
                "retrieve",
            }

        return False


class GuardianStudentPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        action = getattr(view, "action", None)

        if user.role in MANAGEMENT_ROLES:
            return action in {
                "list",
                "retrieve",
                "create",
                "activate",
                "deactivate",
                "destroy",
            }

        return False


class EnrollmentPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        action = getattr(view, "action", None)

        if user.role in MANAGEMENT_ROLES:
            return action in {
                "list",
                "retrieve",
                "create",
                "partial_update",
                "transfer",
                "destroy",
            }

        if user.role == User.Role.TEACHER:
            return action in {
                "list",
                "retrieve",
            }

        return False
