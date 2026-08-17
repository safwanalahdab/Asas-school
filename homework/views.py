from django.contrib.auth import get_user_model
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from accounts.permissions import IsWebDashboardUser
from config.api_responses import ArabicApiResponseMixin

from .models import Homework

from .permissions import CanAccessHomework
from .serializers import HomeworkSerializer

from .filters import HomeworkFilter

User = get_user_model()


class HomeworkViewSet(
    ArabicApiResponseMixin,
    ModelViewSet,
):
    queryset = Homework.objects.select_related(
        "teacher_assignment",
        "teacher_assignment__teacher",
        "teacher_assignment__section",
        "teacher_assignment__grade_subject",
        "teacher_assignment__grade_subject__academic_year",
        "teacher_assignment__grade_subject__grade_level",
        "teacher_assignment__grade_subject__subject",
        "created_by",
    )

    serializer_class = HomeworkSerializer

    permission_classes = [
        IsAuthenticated,
        IsWebDashboardUser,
        CanAccessHomework,
    ]

    filterset_class = HomeworkFilter

    http_method_names = [
        "get",
        "post",
        "patch",
        "delete",
        "head",
        "options",
    ]

    response_messages = {
        "list": (
            "HOMEWORKS_RETRIEVED",
            "تم جلب الواجبات بنجاح.",
        ),
        "retrieve": (
            "HOMEWORK_RETRIEVED",
            "تم جلب الواجب بنجاح.",
        ),
        "create": (
            "HOMEWORK_CREATED",
            "تمت إضافة الواجب بنجاح.",
        ),
        "partial_update": (
            "HOMEWORK_UPDATED",
            "تم تحديث الواجب بنجاح.",
        ),
        "destroy": (
            "HOMEWORK_DELETED",
            "تم حذف الواجب بنجاح.",
        ),
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if user.is_superuser:
            return queryset

        if user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SUPERVISOR,
        }:
            return queryset

        if user.role == User.Role.TEACHER:
            return queryset.filter(
                teacher_assignment__teacher=user,
            )

        return queryset.none()

    def validate_teacher_assignment_access(self, serializer):
        user = self.request.user

        if user.is_superuser:
            return

        if user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SUPERVISOR,
        }:
            return

        if user.role != User.Role.TEACHER:
            return

        teacher_assignment = serializer.validated_data.get(
            "teacher_assignment",
        )

        if (
            teacher_assignment is None
            and serializer.instance is not None
        ):
            teacher_assignment = (
                serializer.instance.teacher_assignment
            )

        if teacher_assignment.teacher_id != user.id:
            raise PermissionDenied(
                {
                    "code": "HOMEWORK_ASSIGNMENT_FORBIDDEN",
                    "detail": (
                        "لا يمكنك استخدام تكليف معلّم آخر "
                        "لإنشاء أو تعديل الواجب."
                    ),
                }
            )

    def perform_create(self, serializer):
        self.validate_teacher_assignment_access(
            serializer,
        )

        serializer.save(
            created_by=self.request.user,
        )

    def perform_update(self, serializer):
        self.validate_teacher_assignment_access(
            serializer,
        )

        serializer.save()