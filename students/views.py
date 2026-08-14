from django.db.models import Q
from django.utils import timezone

from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from config.api_responses import ArabicApiResponseMixin
from audit_logs.mixins import AuditModelViewSetMixin
from audit_logs.models import AuditLog
from audit_logs.services import log_event
from django.db import transaction
from django.db.models.deletion import ProtectedError
from rest_framework.exceptions import ValidationError

from accounts.models import User
from accounts.permissions import IsWebDashboardUser

from .filters import (
    EnrollmentFilter,
    GuardianStudentFilter,
    StudentFilter,
)
from .models import (
    Enrollment,
    GuardianStudent,
    Student,
)
from .permissions import (
    EnrollmentPermission,
    GuardianStudentPermission,
    StudentPermission,
)
from .serializers import (
    EnrollmentSerializer,
    GuardianStudentSerializer,
    StudentSerializer,
    TransferEnrollmentSerializer,
)
from .services import transfer_student_between_sections


class StudentViewSet(ArabicApiResponseMixin, AuditModelViewSetMixin, viewsets.ModelViewSet):
    response_messages = {
        "list": ("STUDENTS_RETRIEVED", "تم جلب قائمة الطلاب بنجاح."),
        "retrieve": ("STUDENT_RETRIEVED", "تم جلب بيانات الطالب بنجاح."),
        "create": ("STUDENT_CREATED", "تمت إضافة الطالب بنجاح."),
        "partial_update": ("STUDENT_UPDATED", "تم تحديث بيانات الطالب بنجاح."),
        "activate": ("STUDENT_ACTIVATED", "تم تفعيل الطالب بنجاح."),
        "deactivate": ("STUDENT_DEACTIVATED", "تم تعطيل الطالب بنجاح."),
        "destroy": ("STUDENT_DELETED", "تم حذف الطالب بنجاح."),
    }
    serializer_class = StudentSerializer

    permission_classes = [
        IsAuthenticated,
        IsWebDashboardUser,
        StudentPermission,
    ]

    http_method_names = [
        "get",
        "post",
        "patch",
        "head",
        "options",
        "delete",
    ]

    queryset = Student.objects.all()

    filter_backends = [
        DjangoFilterBackend,
        OrderingFilter,
    ]

    filterset_class = StudentFilter

    ordering_fields = [
        "first_name",
        "last_name",
        "birth_date",
        "created_at",
    ]

    ordering = [
        "first_name",
        "last_name",
    ]

    def get_queryset(self):
        queryset = super().get_queryset()

        user = self.request.user

        if user.is_superuser or user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SECRETARIAT,
            User.Role.SUPERVISOR,
        }:
            return queryset

        if user.role == User.Role.TEACHER:
            today = timezone.localdate()

            return queryset.filter(
                Q(
                    enrollments__section__teacher_assignments__teacher=user,
                )
                & (
                    Q(
                        enrollments__section__teacher_assignments__end_date__isnull=True,
                    )
                    | Q(
                        enrollments__section__teacher_assignments__end_date__gte=today,
                    )
                )
            ).distinct()

        return queryset.none()

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError as exc:
            raise ValidationError({"code": "STUDENT_DELETE_BLOCKED", "detail": "لا يمكن حذف الطالب لوجود تسجيلات دراسية أو رابط ولي أمر أو سجل انتقال مرتبط به. يمكنك تعطيله مع الاحتفاظ بسجله الدراسي."}) from exc

    @action(
        detail=True,
        methods=["post"],
        url_path="activate",
    )
    def activate(self, request, pk=None):
        student = self.get_object()

        if student.is_active:
            return Response(
                {
                    "code": "student_already_active",
                    "detail": "الطالب فعال بالفعل.",
                },
                status=status.HTTP_200_OK,
            )

        with transaction.atomic():
            student.is_active = True
            student.save(update_fields=["is_active", "updated_at"])
            log_event(actor=request.user, action=AuditLog.Action.ACTIVATE, instance=student, changes={"is_active": {"before": False, "after": True}})

        return Response(
            {
                "code": "student_activated",
                "detail": "تم تفعيل الطالب بنجاح.",
                "data": self.get_serializer(student).data,
            },
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="deactivate",
    )
    def deactivate(self, request, pk=None):
        student = self.get_object()

        if not student.is_active:
            return Response(
                {
                    "code": "student_already_inactive",
                    "detail": "الطالب غير فعال بالفعل.",
                },
                status=status.HTTP_200_OK,
            )

        with transaction.atomic():
            student.is_active = False
            student.save(update_fields=["is_active", "updated_at"])
            log_event(actor=request.user, action=AuditLog.Action.DEACTIVATE, instance=student, changes={"is_active": {"before": True, "after": False}})

        return Response(
            {
                "code": "student_deactivated",
                "detail": "تم تعطيل الطالب بنجاح.",
                "data": self.get_serializer(student).data,
            },
            status=status.HTTP_200_OK,
        )


class GuardianStudentViewSet(ArabicApiResponseMixin, AuditModelViewSetMixin, viewsets.ModelViewSet):
    response_messages = {
        "list": ("GUARDIAN_LINKS_RETRIEVED", "تم جلب روابط أولياء الأمور بالطلاب بنجاح."),
        "retrieve": ("GUARDIAN_LINK_RETRIEVED", "تم جلب رابط ولي الأمر بالطالب بنجاح."),
        "create": ("GUARDIAN_LINK_CREATED", "تم ربط ولي الأمر بالطالب بنجاح."),
        "destroy": (
            "GUARDIAN_LINK_DELETED",
            "تم حذف رابط ولي الأمر بالطالب بنجاح.",
        ),
    }
    serializer_class = GuardianStudentSerializer

    permission_classes = [
        IsAuthenticated,
        IsWebDashboardUser,
        GuardianStudentPermission,
    ]

    http_method_names = [
        "get",
        "post",
        "head",
        "options",
        "delete",
    ]

    queryset = GuardianStudent.objects.select_related(
        "guardian",
        "student",
    ).all()

    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]

    filterset_class = GuardianStudentFilter

    search_fields = [
        "guardian__username",
        "guardian__first_name",
        "guardian__last_name",
        "guardian__email",
        "student__first_name",
        "student__last_name",
    ]

    ordering_fields = [
        "created_at",
        "guardian__first_name",
        "guardian__last_name",
        "student__first_name",
        "student__last_name",
    ]

    ordering = [
        "-created_at",
    ]


class EnrollmentViewSet(ArabicApiResponseMixin, AuditModelViewSetMixin, viewsets.ModelViewSet):
    response_messages = {
        "list": ("ENROLLMENTS_RETRIEVED", "تم جلب قائمة تسجيلات الطلاب بنجاح."),
        "retrieve": ("ENROLLMENT_RETRIEVED", "تم جلب تسجيل الطالب بنجاح."),
        "create": ("ENROLLMENT_CREATED", "تم تسجيل الطالب في السنة والشعبة بنجاح."),
        "partial_update": ("ENROLLMENT_UPDATED", "تم تحديث تسجيل الطالب بنجاح."),
        "transfer": ("STUDENT_TRANSFERRED", "تم نقل الطالب إلى الشعبة الجديدة بنجاح."),
        "destroy": (
            "ENROLLMENT_DELETED",
            "تم حذف تسجيل الطالب بنجاح.",
        ),
    }
    serializer_class = EnrollmentSerializer

    permission_classes = [
        IsAuthenticated,
        IsWebDashboardUser,
        EnrollmentPermission,
    ]

    http_method_names = [
        "get",
        "post",
        "patch",
        "head",
        "options",
        "delete",
    ]

    queryset = Enrollment.objects.select_related(
        "student",
        "academic_year",
        "section",
        "section__grade_level",
    ).all()

    filter_backends = [
        DjangoFilterBackend,
        OrderingFilter,
    ]

    filterset_class = EnrollmentFilter

    ordering_fields = [
        "enrollment_date",
        "created_at",
        "student__first_name",
        "student__last_name",
    ]

    ordering = [
        "-enrollment_date",
    ]

    def get_queryset(self):
        queryset = super().get_queryset()

        user = self.request.user

        if user.is_superuser or user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SECRETARIAT,
            User.Role.SUPERVISOR,
        }:
            return queryset

        if user.role == User.Role.TEACHER:
            today = timezone.localdate()

            return queryset.filter(
                Q(
                    section__teacher_assignments__teacher=user,
                )
                & (
                    Q(
                        section__teacher_assignments__end_date__isnull=True,
                    )
                    | Q(
                        section__teacher_assignments__end_date__gte=today,
                    )
                )
            ).distinct()

        return queryset.none()

    def destroy(self, request, *args, **kwargs):
        enrollment = self.get_object()
        if enrollment.audit_logs.exists():
            raise ValidationError({"code": "ENROLLMENT_DELETE_BLOCKED", "detail": "لا يمكن حذف التسجيل لأنه أصبح جزءًا من سجل انتقالات الطالب."})
        return super().destroy(request, *args, **kwargs)

    def get_serializer_class(self):
        if self.action == "transfer":
            return TransferEnrollmentSerializer

        return EnrollmentSerializer

    @action(
        detail=True,
        methods=["post"],
        url_path="transfer",
    )
    def transfer(self, request, pk=None):
        enrollment = self.get_object()

        serializer = self.get_serializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        target_section = serializer.validated_data["section"]

        transferred_enrollment = transfer_student_between_sections(
            enrollment=enrollment,
            target_section=target_section,
            actor=request.user,
        )

        response_serializer = EnrollmentSerializer(
            transferred_enrollment,
            context=self.get_serializer_context(),
        )

        return Response(
            {
                "code": "STUDENT_TRANSFERRED",
                "detail": "تم نقل الطالب إلى الشعبة الجديدة بنجاح.",
                "data": response_serializer.data,
            },
            status=status.HTTP_200_OK,
        )
