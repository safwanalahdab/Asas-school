from django.contrib.auth import get_user_model
from rest_framework.permissions import BasePermission


User = get_user_model()


class CanAccessBehaviorNotes(BasePermission):
    message = "ليس لديك صلاحية للوصول إلى الملاحظات السلوكية."

    def has_permission(self, request, view):
        user = request.user

        if user.is_superuser:
            return True

        return user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SUPERVISOR,
        }