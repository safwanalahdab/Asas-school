from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from accounts.permissions import ActionBusinessPermission, PasswordChangeGate
from academics.supervisor_academic_scope import (
    can_access_section,
    filter_queryset_by_stage,
    is_stage_scoped_supervisor,
)
from config.api_responses import ArabicApiResponseMixin

from .models import Homework
from .permissions import IsWebClientToken

from .serializers import HomeworkSerializer
from .services import notify_homework_created

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
    action_permissions = {
        "list": "homework.view_homework",
        "retrieve": "homework.view_homework",
        "create": "homework.add_homework",
        "partial_update": "homework.change_homework",
        "destroy": "homework.delete_homework",
    }

    permission_classes = [
        IsAuthenticated,
        PasswordChangeGate,
        IsWebClientToken,
        ActionBusinessPermission,
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

        if user.role == User.Role.TEACHER:
            return queryset.filter(
                teacher_assignment__teacher=user,
            )

        if is_stage_scoped_supervisor(user):
            queryset = queryset.filter(
                teacher_assignment__section__grade_level_id=F(
                    "teacher_assignment__grade_subject__grade_level_id"
                ),
                teacher_assignment__section__academic_year_id=F(
                    "teacher_assignment__grade_subject__academic_year_id"
                ),
            )
            return filter_queryset_by_stage(
                queryset, user,
                stage_lookup="teacher_assignment__section__grade_level__stage",
            )

        return queryset

    def validate_supervisor_assignment_scope(self, serializer):
        user = self.request.user
        if not is_stage_scoped_supervisor(user):
            return

        assignment = serializer.validated_data.get("teacher_assignment")
        if assignment is None:
            return

        section = assignment.section
        grade_subject = assignment.grade_subject
        if (
            section.grade_level_id != grade_subject.grade_level_id
            or section.academic_year_id != grade_subject.academic_year_id
            or not can_access_section(user, section)
        ):
            raise PermissionDenied({
                "code": "SUPERVISOR_ACADEMIC_SCOPE_DENIED",
                "detail": "التكليف المحدد خارج نطاق مراحل الموجّه أو غير متسق أكاديميًا.",
            })

    def validate_teacher_assignment_access(self, serializer):
        user = self.request.user

        if user.is_superuser:
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

    @transaction.atomic
    def perform_create(self, serializer):
        self.validate_supervisor_assignment_scope(serializer)
        self.validate_teacher_assignment_access(
            serializer,
        )

        homework = serializer.save(
            created_by=self.request.user,
        )
        notify_homework_created(homework)

    def perform_update(self, serializer):
        self.validate_supervisor_assignment_scope(serializer)
        self.validate_teacher_assignment_access(
            serializer,
        )

        serializer.save()
