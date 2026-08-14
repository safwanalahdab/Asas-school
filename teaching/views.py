from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response
from config.api_responses import ArabicApiResponseMixin
from audit_logs.mixins import AuditModelViewSetMixin
from audit_logs.models import AuditLog
from audit_logs.services import log_event
from django.db import transaction

from accounts.models import User
from accounts.permissions import IsWebDashboardUser

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter, SearchFilter
from .filters import TeacherAssignmentFilter

from .models import TeacherAssignment
from .permissions import TeachingAssignmentPermission
from .serializers import TeacherAssignmentSerializer


class TeacherAssignmentViewSet(ArabicApiResponseMixin, AuditModelViewSetMixin, viewsets.ModelViewSet):
    response_messages = {
        "list": ("TEACHER_ASSIGNMENTS_RETRIEVED", "تم جلب قائمة تكليفات المعلمين بنجاح."),
        "retrieve": ("TEACHER_ASSIGNMENT_RETRIEVED", "تم جلب تكليف المعلم بنجاح."),
        "create": ("TEACHER_ASSIGNMENT_CREATED", "تم إنشاء تكليف المعلم بنجاح."),
        "partial_update": ("TEACHER_ASSIGNMENT_UPDATED", "تم تحديث تكليف المعلم بنجاح."),
        "end": ("TEACHER_ASSIGNMENT_ENDED", "تم إنهاء تكليف المعلّم بنجاح."),
        "reopen": ("TEACHER_ASSIGNMENT_REOPENED", "تمت إعادة فتح تكليف المعلّم بنجاح."),
        "destroy": (
            "TEACHER_ASSIGNMENT_DELETED",
            "تم حذف تكليف المعلّم بنجاح.",
        ),
    }
    serializer_class = TeacherAssignmentSerializer

    permission_classes = [
        IsAuthenticated,
        IsWebDashboardUser,
        TeachingAssignmentPermission,
    ]
    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]

    filterset_class = TeacherAssignmentFilter

    search_fields = [
        "teacher__username",
        "teacher__first_name",
        "teacher__last_name",
        "grade_subject__subject__name",
        "grade_subject__grade_level__name",
        "section__name",
    ]

    ordering_fields = [
        "start_date",
        "end_date",
        "created_at",
        "teacher__first_name",
        "teacher__last_name",
    ]

    ordering = [
        "-start_date",
    ]

    http_method_names = [
        "get",
        "post",
        "patch",
        "head",
        "options",
        "delete",
    ]

    queryset = TeacherAssignment.objects.select_related(
        "teacher",
        "grade_subject",
        "grade_subject__academic_year",
        "grade_subject__grade_level",
        "grade_subject__subject",
        "section",
        "section__academic_year",
        "section__grade_level",
    ).all()

    def get_queryset(self):
        queryset = super().get_queryset()

        user = self.request.user

        if not user.is_superuser and user.role == User.Role.TEACHER:
            return queryset.filter(
                teacher=user,
            )

        return queryset

    @action(
        detail=True,
        methods=["post"],
        url_path="end",
    )
    def end(self, request, pk=None):
        assignment = self.get_object()

        if assignment.end_date is not None:
            raise ValidationError(
                {
                    "code": "TEACHER_ASSIGNMENT_ALREADY_ENDED",
                    "detail": "تعذّر إنهاء التكليف، لأنه منتهٍ بالفعل.",
                    "end_date": ("هذا التكليف منتهٍ بالفعل."),
                }
            )

        end_date = request.data.get("end_date")

        if not end_date:
            raise ValidationError(
                {
                    "end_date": ("تاريخ نهاية التكليف مطلوب."),
                }
            )

        serializer = self.get_serializer(
            assignment,
            data={
                "end_date": end_date,
            },
            partial=True,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        with transaction.atomic():
            serializer.save()
            log_event(actor=request.user, action=AuditLog.Action.END, instance=assignment, changes={"end_date": {"before": None, "after": serializer.validated_data["end_date"]}})

        return Response(
            {
                "code": "TEACHER_ASSIGNMENT_ENDED",
                "detail": "تم إنهاء تكليف المعلّم بنجاح.",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="reopen")
    def reopen(self, request, pk=None):
        assignment = self.get_object()
        if assignment.end_date is None:
            raise ValidationError({"code": "TEACHER_ASSIGNMENT_ALREADY_ACTIVE", "detail": "تعذّرت إعادة فتح التكليف، لأنه فعال بالفعل.", "end_date": "التكليف غير منتهٍ."})
        serializer = self.get_serializer(assignment, data={"end_date": None}, partial=True)
        serializer.is_valid(raise_exception=True)
        previous_end_date = assignment.end_date
        with transaction.atomic():
            serializer.save()
            log_event(actor=request.user, action=AuditLog.Action.REOPEN, instance=assignment, changes={"end_date": {"before": previous_end_date, "after": None}})
        return Response({"code": "TEACHER_ASSIGNMENT_REOPENED", "detail": "تمت إعادة فتح تكليف المعلّم بنجاح.", "data": serializer.data}, status=status.HTTP_200_OK)
