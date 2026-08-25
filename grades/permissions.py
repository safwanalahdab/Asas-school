from django.contrib.auth import get_user_model

from rest_framework.permissions import BasePermission

from .services import teacher_has_active_assignment


User = get_user_model()


class CanAccessGrades(BasePermission):
    message = (
        "ليس لديك صلاحية للوصول إلى "
        "وحدة العلامات والتقييمات."
    )

    def has_permission(
        self,
        request,
        view,
    ):
        user = request.user

        if (
            not user
            or not user.is_authenticated
        ):
            return False

        if user.is_superuser:
            return True

        return user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SUPERVISOR,
            User.Role.TEACHER,
        }

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
            User.Role.SUPERVISOR,
        }:
            return True

        if user.role == User.Role.TEACHER:
            return any(
                teacher_has_active_assignment(teacher=user, section=link.section, grade_subject=obj.grade_subject)
                for link in obj.assessment_sections.all()
            )

        return False


class CanPublishGrades(BasePermission):
    message = (
        "اعتماد ونشر النتائج متاح للإدارة "
        "والموجّه التربوي فقط."
    )

    def has_permission(
        self,
        request,
        view,
    ):
        user = request.user

        if (
            not user
            or not user.is_authenticated
        ):
            return False

        if user.is_superuser:
            return True

        return user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SUPERVISOR,
        }


class CanCreateGradeWideAssessment(
    BasePermission,
):
    message = (
        "إنشاء تقييم لجميع شعب الصف متاح "
        "للإدارة والموجّه التربوي فقط."
    )

    def has_permission(
        self,
        request,
        view,
    ):
        user = request.user

        if (
            not user
            or not user.is_authenticated
        ):
            return False

        if user.is_superuser:
            return True

        return user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SUPERVISOR,
        }
