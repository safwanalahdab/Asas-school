from django.contrib.auth import get_user_model
from rest_framework.permissions import BasePermission


User = get_user_model()


class CanAccessSchoolRequests(BasePermission):
    message = {
        "code": "SCHOOL_REQUEST_ACCESS_DENIED",
        "detail": "ليس لديك صلاحية للوصول إلى الطلبات.",
    }

    def has_permission(self, request, view):
        user = request.user
        action = getattr(view, "action", None)

        if user.is_superuser:
            return action in {
                "list",
                "retrieve",
                "answer",
            }

        if user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SUPERVISOR,
            User.Role.SECRETARIAT,
        }:
            return action in {
                "list",
                "retrieve",
                "answer",
            }

        if user.role == User.Role.GUARDIAN:
            return action in {
                "list",
                "retrieve",
                "create",
            }

        return False

    def has_object_permission(self, request, view, obj):
        user = request.user
        action = getattr(view, "action", None)

        if user.is_superuser:
            return action in {
                "retrieve",
                "answer",
            }

        if user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SUPERVISOR,
            User.Role.SECRETARIAT,
        }:
            return action in {
                "retrieve",
                "answer",
            }

        if user.role == User.Role.GUARDIAN:
            return (
                action == "retrieve"
                and obj.guardian_id == user.id
            )

        return False