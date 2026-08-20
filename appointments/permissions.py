from django.contrib.auth import get_user_model

from rest_framework.permissions import BasePermission


User = get_user_model()


class CanAccessAppointments(BasePermission):
    message = {
        "code": "APPOINTMENT_ACCESS_DENIED",
        "detail": "ليس لديك صلاحية للوصول إلى طلبات المواعيد.",
    }

    def has_permission(self, request, view):
        user = request.user
        action = getattr(
            view,
            "action",
            None,
        )

        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return action in {
                "list",
                "retrieve",
                "approve",
                "reject",
            }

        if user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SECRETARIAT,
        }:
            return action in {
                "list",
                "retrieve",
                "approve",
                "reject",
            }

        if user.role == User.Role.GUARDIAN:
            return action in {
                "list",
                "retrieve",
                "create",
            }

        return False

    def has_object_permission(
        self,
        request,
        view,
        obj,
    ):
        user = request.user
        action = getattr(
            view,
            "action",
            None,
        )

        if user.is_superuser:
            return action in {
                "retrieve",
                "approve",
                "reject",
            }

        if user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SECRETARIAT,
        }:
            return action in {
                "retrieve",
                "approve",
                "reject",
            }

        if user.role == User.Role.GUARDIAN:
            return (
                action == "retrieve"
                and obj.guardian_id == user.id
            )

        return False