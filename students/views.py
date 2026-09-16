from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, inline_serializer

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from config.api_responses import ArabicApiResponseMixin, success_response
from audit_logs.models import AuditLog
from audit_logs.services import get_actor_display, record_audit_event
from django.db import transaction
from django.db.models.deletion import ProtectedError
from rest_framework.exceptions import ValidationError

from accounts.models import User
from accounts.permissions import ActionBusinessPermission, PasswordChangeGate
from behavior.permissions import IsWebClientToken

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
from .health_serializers import StudentHealthProfileSerializer
from .registration_serializers import StudentRegistrationSerializer
from .serializers import (
    EnrollmentSerializer,
    GuardianStudentSerializer,
    StudentSerializer,
    TransferEnrollmentSerializer,
)
from .services import (
    ensure_student_health_profile,
    register_student,
    transfer_student_between_sections,
)

from finance.services import (
    ensure_financial_account_for_enrollment,
)


class _AtomicCrudMixin:
    @transaction.atomic
    def perform_create(self, serializer):
        serializer.save()

    @transaction.atomic
    def perform_update(self, serializer):
        serializer.save()

    @transaction.atomic
    def perform_destroy(self, instance):
        instance.delete()


class StudentRegistrationView(ArabicApiResponseMixin, APIView):
    permission_classes = [
        IsAuthenticated,
        PasswordChangeGate,
        IsWebClientToken,
        ActionBusinessPermission,
    ]
    method_permissions = {
        "post": "students.register_student",
    }

    @extend_schema(
        request=StudentRegistrationSerializer,
        responses={
            status.HTTP_201_CREATED: inline_serializer(
                name="StudentRegistrationResponse",
                fields={
                    "student": StudentSerializer(),
                    "guardian_account": inline_serializer(
                        name="StudentRegistrationGuardianAccountResponse",
                        fields={
                            "status": serializers.ChoiceField(
                                choices=(
                                    "created",
                                    "linked_existing",
                                    "not_created",
                                )
                            ),
                            "username": serializers.CharField(allow_null=True),
                            "temporary_password": serializers.CharField(
                                allow_null=True
                            ),
                        },
                    ),
                },
            ),
        },
    )
    def post(self, request):
        serializer = StudentRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        result = register_student(
            student_data=validated_data["student"],
            health_profile_data=validated_data.get("health_profile"),
            guardian_data=validated_data.get("guardian"),
        )

        return success_response(
            code="STUDENT_REGISTERED",
            message="تم تسجيل الطالب بنجاح.",
            data={
                "student": StudentSerializer(
                    result["student"],
                    context={"request": request},
                ).data,
                "guardian_account": result["guardian_account"],
            },
            status_code=status.HTTP_201_CREATED,
        )


class StudentHealthProfileView(ArabicApiResponseMixin, APIView):
    permission_classes = [
        IsAuthenticated,
        PasswordChangeGate,
        IsWebClientToken,
        ActionBusinessPermission,
    ]
    method_permissions = {
        "get": "students.view_studenthealthprofile",
        "patch": "students.change_studenthealthprofile",
    }
    http_method_names = ["get", "patch", "head", "options"]
    response_messages = {
        "get": (
            "HEALTH_PROFILE_RETRIEVED",
            "تم جلب الملف الصحي للطالب بنجاح.",
        ),
        "patch": (
            "HEALTH_PROFILE_UPDATED",
            "تم تحديث الملف الصحي للطالب بنجاح.",
        ),
    }

    def get_profile(self):
        student = get_object_or_404(Student, pk=self.kwargs["student_id"])
        return ensure_student_health_profile(student)

    @extend_schema(responses=StudentHealthProfileSerializer)
    def get(self, request, student_id):
        serializer = StudentHealthProfileSerializer(
            self.get_profile(),
            context={"request": request},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        request=StudentHealthProfileSerializer,
        responses=StudentHealthProfileSerializer,
    )
    @transaction.atomic
    def patch(self, request, student_id):
        serializer = StudentHealthProfileSerializer(
            self.get_profile(),
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


class StudentViewSet(
    ArabicApiResponseMixin, _AtomicCrudMixin, viewsets.ModelViewSet
):
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
        PasswordChangeGate,
        IsWebClientToken,
        ActionBusinessPermission,
    ]

    action_permissions = {
        "list": "students.view_student",
        "retrieve": "students.view_student",
        "create": "students.add_student",
        "partial_update": "students.change_student",
        "activate": "students.change_student",
        "deactivate": "students.change_student",
        "destroy": "students.delete_student",
    }

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

    @transaction.atomic
    def perform_create(self, serializer):
        student = serializer.save()
        ensure_student_health_profile(student)

    def get_queryset(self):
        queryset = super().get_queryset()

        user = self.request.user

        if user.is_superuser or user.role != User.Role.TEACHER:
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
            raise ValidationError(
                {
                    "code": "STUDENT_DELETE_BLOCKED",
                    "detail": "لا يمكن حذف الطالب لوجود تسجيلات دراسية أو رابط ولي أمر أو سجل انتقال مرتبط به. يمكنك تعطيله مع الاحتفاظ بسجله الدراسي.",
                }
            ) from exc

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

        return Response(
            {
                "code": "student_deactivated",
                "detail": "تم تعطيل الطالب بنجاح.",
                "data": self.get_serializer(student).data,
            },
            status=status.HTTP_200_OK,
        )


class GuardianStudentViewSet(
    ArabicApiResponseMixin, _AtomicCrudMixin, viewsets.ModelViewSet
):
    response_messages = {
        "list": (
            "GUARDIAN_LINKS_RETRIEVED",
            "تم جلب روابط أولياء الأمور بالطلاب بنجاح.",
        ),
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
        PasswordChangeGate,
        IsWebClientToken,
        ActionBusinessPermission,
    ]

    action_permissions = {
        "list": "students.view_guardianstudent",
        "retrieve": "students.view_guardianstudent",
        "create": "students.add_guardianstudent",
        "destroy": "students.delete_guardianstudent",
    }

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

    @transaction.atomic
    def perform_create(self, serializer):
        link = serializer.save()
        actor_name = get_actor_display(self.request.user)
        record_audit_event(
            actor=self.request.user, module=AuditLog.Module.STUDENTS,
            action=AuditLog.Action.CREATE,
            message=f"ربط {actor_name} ولي الأمر {link.guardian} بالطالب {link.student.full_name}.",
            target=link,
            metadata={"guardian": str(link.guardian), "student": link.student.full_name},
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        target_id, target_display = instance.pk, str(instance)
        guardian, student = str(instance.guardian), instance.student.full_name
        instance.delete()
        actor_name = get_actor_display(self.request.user)
        record_audit_event(
            actor=self.request.user, module=AuditLog.Module.STUDENTS,
            action=AuditLog.Action.DELETE,
            message=f"فكّ {actor_name} ارتباط ولي الأمر {guardian} بالطالب {student}.",
            target_type="students.GuardianStudent", target_id=target_id,
            target_display=target_display,
            metadata={"guardian": guardian, "student": student},
        )


class EnrollmentViewSet(
    ArabicApiResponseMixin, _AtomicCrudMixin, viewsets.ModelViewSet
):
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
        PasswordChangeGate,
        IsWebClientToken,
        ActionBusinessPermission,
    ]

    action_permissions = {
        "list": "students.view_enrollment",
        "retrieve": "students.view_enrollment",
        "create": "students.add_enrollment",
        "partial_update": "students.change_enrollment",
        "transfer": "students.transfer_student",
        "destroy": "students.delete_enrollment",
    }

    http_method_names = [
        "get",
        "post",
        "patch",
        "head",
        "options",
        "delete",
    ]

    @transaction.atomic
    def perform_create(self, serializer):
        enrollment = serializer.save()

        ensure_financial_account_for_enrollment(
            enrollment=enrollment,
            actor=self.request.user,
        )
        actor_name = get_actor_display(self.request.user)
        record_audit_event(
            actor=self.request.user, module=AuditLog.Module.STUDENTS,
            action=AuditLog.Action.CREATE,
            message=f"سجّل {actor_name} الطالب {enrollment.student.full_name} في {enrollment.section} للسنة الدراسية {enrollment.academic_year}.",
            target=enrollment,
            metadata={
                "student": enrollment.student.full_name,
                "academic_year": str(enrollment.academic_year),
                "section": str(enrollment.section),
            },
        )

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

        if user.is_superuser or user.role != User.Role.TEACHER:
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
            raise ValidationError(
                {
                    "code": "ENROLLMENT_DELETE_BLOCKED",
                    "detail": "لا يمكن حذف التسجيل لأنه أصبح جزءًا من سجل انتقالات الطالب.",
                }
            )
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
