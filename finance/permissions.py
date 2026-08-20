from django.contrib.auth import get_user_model

from rest_framework.permissions import BasePermission

from students.models import GuardianStudent


User = get_user_model()


class CanManageTuitionPlans(BasePermission):
    message = {
        "code": "FINANCE_TUITION_ACCESS_DENIED",
        "detail": (
            "ليس لديك صلاحية لإدارة "
            "أسعار الرسوم المدرسية."
        ),
    }

    def has_permission(
        self,
        request,
        view,
    ):
        user = request.user
        action = getattr(
            view,
            "action",
            None,
        )

        allowed_actions = {
            "list",
            "retrieve",
            "create",
            "partial_update",
        }

        if user.is_superuser:
            return action in allowed_actions

        if (
            user.role
            == User.Role.SCHOOL_ADMIN
        ):
            return action in allowed_actions

        return False


class CanAccessFinancialAccounts(
    BasePermission
):
    message = {
        "code": "FINANCE_ACCESS_DENIED",
        "detail": (
            "ليس لديك صلاحية للوصول "
            "إلى البيانات المالية."
        ),
    }

    def has_permission(
        self,
        request,
        view,
    ):
        user = request.user
        action = getattr(
            view,
            "action",
            None,
        )

        admin_actions = {
            "list",
            "retrieve",
            "add_discount",
            "cancel_discount",
            "record_payment",
            "cancel_payment",
            "remaining_syp_preview",
        }

        secretariat_actions = {
            "list",
            "retrieve",
            "record_payment",
            "remaining_syp_preview",
        }

        guardian_actions = {
            "list",
            "retrieve",
            "remaining_syp_preview",
        }

        if user.is_superuser:
            return action in admin_actions

        if (
            user.role
            == User.Role.SCHOOL_ADMIN
        ):
            return action in admin_actions

        if (
            user.role
            == User.Role.SECRETARIAT
        ):
            return action in secretariat_actions

        if (
            user.role
            == User.Role.GUARDIAN
        ):
            return action in guardian_actions

        return False

    def has_object_permission(
        self,
        request,
        view,
        obj,
    ):
        user = request.user

        if user.is_superuser:
            return True

        if user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SECRETARIAT,
        }:
            return True

        if (
            user.role
            == User.Role.GUARDIAN
        ):
            return (
                GuardianStudent.objects
                .filter(
                    guardian=user,
                    student=(
                        obj.enrollment.student
                    ),
                    is_active=True,
                    student__is_active=True,
                )
                .exists()
            )

        return False