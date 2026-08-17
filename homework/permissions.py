from django.contrib.auth import get_user_model
from rest_framework.permissions import BasePermission


User = get_user_model()


class CanAccessHomework(BasePermission):
    message = "ليس لديك صلاحية للوصول إلى الواجبات."

    def has_permission(self, request, view):
        user = request.user

        if user.is_superuser:
            return True

        return user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SUPERVISOR,
            User.Role.TEACHER,
        }

    def has_object_permission(self, request, view, obj):
        user = request.user

        if user.is_superuser:
            return True

        if user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SUPERVISOR,
        }:
            return True

        if user.role == User.Role.TEACHER:
            return obj.teacher_assignment.teacher_id == user.id

        return False