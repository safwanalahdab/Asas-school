from django.db import transaction

from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from rest_framework.viewsets import ModelViewSet

from accounts.permissions import ActionBusinessPermission, PasswordChangeGate
from academics.supervisor_academic_scope import (
    can_access_enrollment,
    filter_queryset_by_stage,
)
from academics.teacher_student_scope import (
    can_teacher_access_enrollment,
    filter_enrollments_by_teacher_scope,
    teacher_student_scope_applies,
)
from students.models import Enrollment

from .filters import BehaviorNoteFilter, StudentPointEntryFilter
from .models import BehaviorNote, StudentPointEntry
from .permissions import IsWebClientToken
from .serializers import BehaviorNoteSerializer, StudentPointEntrySerializer
from .services import (
    notify_behavior_note_created,
    notify_student_point_entry_created,
)
from config.api_responses import ArabicApiResponseMixin


TEACHER_STUDENT_SCOPE_DENIED = {
    "code": "TEACHER_STUDENT_SCOPE_DENIED",
    "detail": "التسجيل المحدد خارج نطاق طلاب المعلّم.",
}


def require_teacher_enrollment_scope(user, enrollment):
    if not can_teacher_access_enrollment(user, enrollment):
        raise PermissionDenied(TEACHER_STUDENT_SCOPE_DENIED)


class BehaviorNoteViewSet(
    ArabicApiResponseMixin,
    ModelViewSet,
):
    queryset = BehaviorNote.objects.select_related(
        "enrollment",
        "created_by",
    )

    serializer_class = BehaviorNoteSerializer
    filterset_class = BehaviorNoteFilter
    action_permissions = {
        "list": "behavior.view_behaviornote",
        "retrieve": "behavior.view_behaviornote",
        "create": "behavior.add_behaviornote",
        "partial_update": "behavior.change_behaviornote",
        "destroy": "behavior.delete_behaviornote",
    }

    permission_classes = [
        IsAuthenticated,
        PasswordChangeGate,
        IsWebClientToken,
        ActionBusinessPermission,
    ]

    http_method_names = [
        "get",
        "post",
        "patch",
        "head",
        "options",
        "delete",
    ]
    response_messages = {
        "list": (
            "BEHAVIOR_NOTES_RETRIEVED",
            "تم جلب الملاحظات السلوكية بنجاح.",
        ),
        "retrieve": (
            "BEHAVIOR_NOTE_RETRIEVED",
            "تم جلب الملاحظة السلوكية بنجاح.",
        ),
        "create": (
            "BEHAVIOR_NOTE_CREATED",
            "تمت إضافة الملاحظة السلوكية بنجاح.",
        ),
        "partial_update": (
            "BEHAVIOR_NOTE_UPDATED",
            "تم تحديث الملاحظة السلوكية بنجاح.",
        ),
        "destroy": (
            "BEHAVIOR_NOTE_DELETED",
            "تم حذف الملاحظة السلوكية بنجاح.",
        ),
    }

    def get_queryset(self):
        queryset = filter_queryset_by_stage(
            super().get_queryset(), self.request.user,
            stage_lookup="enrollment__section__grade_level__stage",
        )
        if teacher_student_scope_applies(self.request.user):
            enrollments = filter_enrollments_by_teacher_scope(
                Enrollment.objects.all(),
                self.request.user,
            )
            queryset = queryset.filter(enrollment__in=enrollments)
        return queryset

    @staticmethod
    def _require_enrollment_scope(user, enrollment):
        if not can_access_enrollment(user, enrollment):
            raise PermissionDenied({
                "code": "SUPERVISOR_ACADEMIC_SCOPE_DENIED",
                "detail": "التسجيل المحدد خارج نطاق مراحل الموجّه.",
            })

    @transaction.atomic
    def perform_create(self, serializer):
        enrollment = serializer.validated_data["enrollment"]
        self._require_enrollment_scope(
            self.request.user, enrollment
        )
        require_teacher_enrollment_scope(self.request.user, enrollment)
        behavior_note = serializer.save(
            created_by=self.request.user,
        )
        notify_behavior_note_created(behavior_note)

    def perform_update(self, serializer):
        enrollment = serializer.validated_data.get("enrollment")
        if enrollment is not None and enrollment.pk != serializer.instance.enrollment_id:
            self._require_enrollment_scope(self.request.user, enrollment)
            require_teacher_enrollment_scope(self.request.user, enrollment)
        serializer.save()


class StudentPointEntryViewSet(
    ArabicApiResponseMixin,
    ModelViewSet,
):
    queryset = StudentPointEntry.objects.select_related(
        "enrollment",
        "enrollment__student",
        "enrollment__academic_year",
        "enrollment__section",
        "enrollment__section__grade_level",
        "created_by",
    )
    serializer_class = StudentPointEntrySerializer
    filterset_class = StudentPointEntryFilter
    search_fields = [
        "enrollment__student__first_name",
        "enrollment__student__last_name",
        "note",
    ]
    ordering_fields = [
        "occurred_on",
        "created_at",
        "points",
    ]
    action_permissions = {
        "list": "behavior.view_studentpointentry",
        "retrieve": "behavior.view_studentpointentry",
        "create": "behavior.add_studentpointentry",
        "partial_update": "behavior.change_studentpointentry",
        "destroy": "behavior.delete_studentpointentry",
    }
    permission_classes = [
        IsAuthenticated,
        PasswordChangeGate,
        IsWebClientToken,
        ActionBusinessPermission,
    ]
    http_method_names = [
        "get",
        "post",
        "patch",
        "head",
        "options",
        "delete",
    ]
    response_messages = {
        "list": (
            "STUDENT_POINTS_RETRIEVED",
            "تم جلب نقاط الطلاب بنجاح.",
        ),
        "retrieve": (
            "STUDENT_POINT_RETRIEVED",
            "تم جلب سجل النقاط بنجاح.",
        ),
        "create": (
            "STUDENT_POINT_CREATED",
            "تمت إضافة نقاط الطالب بنجاح.",
        ),
        "partial_update": (
            "STUDENT_POINT_UPDATED",
            "تم تحديث سجل النقاط بنجاح.",
        ),
        "destroy": (
            "STUDENT_POINT_DELETED",
            "تم حذف سجل النقاط بنجاح.",
        ),
    }

    def get_queryset(self):
        queryset = filter_queryset_by_stage(
            super().get_queryset(),
            self.request.user,
            stage_lookup="enrollment__section__grade_level__stage",
        )
        if teacher_student_scope_applies(self.request.user):
            enrollments = filter_enrollments_by_teacher_scope(
                Enrollment.objects.all(),
                self.request.user,
            )
            queryset = queryset.filter(enrollment__in=enrollments)
        return queryset

    @staticmethod
    def _require_enrollment_scope(user, enrollment):
        if not can_access_enrollment(user, enrollment):
            raise PermissionDenied({
                "code": "SUPERVISOR_ACADEMIC_SCOPE_DENIED",
                "detail": "التسجيل المحدد خارج نطاق مراحل الموجّه.",
            })

    @transaction.atomic
    def perform_create(self, serializer):
        enrollment = serializer.validated_data["enrollment"]
        self._require_enrollment_scope(
            self.request.user,
            enrollment,
        )
        require_teacher_enrollment_scope(self.request.user, enrollment)
        point_entry = serializer.save(created_by=self.request.user)
        notify_student_point_entry_created(point_entry)

    def perform_update(self, serializer):
        enrollment = serializer.validated_data.get("enrollment")
        if enrollment is not None and enrollment.pk != serializer.instance.enrollment_id:
            self._require_enrollment_scope(self.request.user, enrollment)
            require_teacher_enrollment_scope(self.request.user, enrollment)
        serializer.save()
