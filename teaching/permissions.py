from rest_framework.permissions import BasePermission

from accounts.models import User


class TeachingAssignmentPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        action = getattr(view, "action", None)

        if user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SECRETARIAT,
            User.Role.SUPERVISOR,
        }:
            return action in {
                "list",
                "retrieve",
                "create",
                "partial_update",
                "end",
            }

        if user.role == User.Role.TEACHER:
            return action in {
                "list",
                "retrieve",
            }

        return False