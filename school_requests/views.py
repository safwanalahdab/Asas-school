from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.decorators import action
from rest_framework.mixins import (
    CreateModelMixin,
    ListModelMixin,
    RetrieveModelMixin,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from .filters import SchoolRequestFilter

from accounts.permissions import ActionBusinessPermission, PasswordChangeGate
from academics.supervisor_academic_scope import (
    filter_students_by_supervisor_scope,
    supervisor_academic_scope_for,
)
from config.api_responses import ArabicApiResponseMixin
from students.models import Student

from .models import SchoolRequest
from .permissions import WebGuardianSchoolRequestPermission
from .serializers import (
    AnswerSchoolRequestSerializer,
    SchoolRequestSerializer,
)
from .services import notify_school_request_answered


User = get_user_model()


class SchoolRequestViewSet(
    ArabicApiResponseMixin,
    CreateModelMixin,
    ListModelMixin,
    RetrieveModelMixin,
    GenericViewSet,
):
    queryset = (
        SchoolRequest.objects
        .select_related(
            "guardian",
            "student",
            "handled_by",
        )
    )

    permission_classes = [
        IsAuthenticated,
        PasswordChangeGate,
        ActionBusinessPermission,
    ]

    action_permissions = {
        "list": "school_requests.view_schoolrequest",
        "retrieve": "school_requests.view_schoolrequest",
        "answer": "school_requests.reply_to_request",
    }

    filterset_class = SchoolRequestFilter

    http_method_names = [
        "get",
        "post",
        "head",
        "options",
    ]

    response_messages = {
        "list": (
            "SCHOOL_REQUESTS_RETRIEVED",
            "تم جلب الطلبات بنجاح.",
        ),
        "retrieve": (
            "SCHOOL_REQUEST_RETRIEVED",
            "تم جلب الطلب بنجاح.",
        ),
        "create": (
            "SCHOOL_REQUEST_CREATED",
            "تم إرسال الطلب بنجاح.",
        ),
        "answer": (
            "SCHOOL_REQUEST_ANSWERED",
            "تمت الإجابة على الطلب بنجاح.",
        ),
    }

    def get_permissions(self):
        user = getattr(self.request, "user", None)
        if (
            user
            and user.is_authenticated
            and user.role == User.Role.GUARDIAN
        ):
            permission_classes = [
                IsAuthenticated,
                PasswordChangeGate,
                WebGuardianSchoolRequestPermission,
            ]
            return [permission() for permission in permission_classes]
        return super().get_permissions()

    def get_serializer_class(self):
        if self.action == "answer":
            return AnswerSchoolRequestSerializer

        return SchoolRequestSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if user.role == User.Role.GUARDIAN:
            return queryset.filter(
                guardian=user,
            )

        if user.role == User.Role.SUPERVISOR and not user.is_superuser:
            if supervisor_academic_scope_for(user).allows_all_stages:
                return queryset
            eligible_students = filter_students_by_supervisor_scope(
                Student.objects.all(), user
            ).values("pk")
            return queryset.filter(student_id__in=eligible_students)

        return queryset

    def perform_create(self, serializer):
        serializer.save(
            guardian=self.request.user,
            status=SchoolRequest.Status.NEW,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="answer",
    )
    def answer(self, request, pk=None):
        with transaction.atomic():
            school_request = get_object_or_404(
                self.get_queryset().select_for_update(of=("self",)),
                pk=pk,
            )

            self.check_object_permissions(
                request,
                school_request,
            )

            if school_request.status == SchoolRequest.Status.ANSWERED:
                from rest_framework.exceptions import ValidationError

                raise ValidationError(
                    {
                        "school_response": (
                            "تمت الإجابة على هذا الطلب مسبقًا."
                        )
                    }
                )

            serializer = self.get_serializer(
                data=request.data,
            )

            serializer.is_valid(
                raise_exception=True,
            )

            school_request.school_response = (
                serializer.validated_data[
                    "school_response"
                ]
            )

            school_request.status = (
                SchoolRequest.Status.ANSWERED
            )

            school_request.handled_by = request.user

            school_request.answered_at = timezone.now()

            school_request.save(
                update_fields=[
                    "school_response",
                    "status",
                    "handled_by",
                    "answered_at",
                    "updated_at",
                ]
            )

            notify_school_request_answered(school_request)

        response_serializer = SchoolRequestSerializer(
            school_request,
            context=self.get_serializer_context(),
        )

        return Response(
            response_serializer.data,
        )
