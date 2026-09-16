from rest_framework.permissions import BasePermission

from accounts.models import User


class WebGuardianSchoolRequestPermission(BasePermission):
    """Preserve the existing guardian-owned web flow; staff uses business permissions."""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.role == User.Role.GUARDIAN
            and getattr(view, "action", None) in {"list", "retrieve", "create"}
        )

    def has_object_permission(self, request, view, obj):
        return bool(
            getattr(view, "action", None) == "retrieve"
            and obj.guardian_id == request.user.id
        )
