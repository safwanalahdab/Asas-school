from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from accounts.permissions import ActionBusinessPermission, PasswordChangeGate
from academics.models import AcademicYear
from academics.models import GradeLevel, Section
from academics.supervisor_academic_scope import (
    can_access_grade_level,
    can_access_section,
    supervisor_academic_scope_for,
)
from rest_framework.exceptions import PermissionDenied
from config.api_responses import ArabicApiResponseMixin
from students.models import Enrollment
from teaching.models import TeacherAssignment

from .filters import AnnouncementFilter
from .models import Announcement
from .serializers import AnnouncementSerializer
from .services import notify_announcement_published


User = get_user_model()


class AnnouncementViewSet(
    ArabicApiResponseMixin,
    ModelViewSet,
):
    queryset = (
        Announcement.objects
        .select_related(
            "created_by",
        )
        .prefetch_related(
            "grade_levels",
            "sections__grade_level",
        )
    )

    serializer_class = AnnouncementSerializer
    action_permissions = {
        "list": "announcements.view_announcement",
        "retrieve": "announcements.view_announcement",
        "create": "announcements.add_announcement",
        "partial_update": "announcements.change_announcement",
        "destroy": "announcements.delete_announcement",
    }

    permission_classes = [
        IsAuthenticated,
        PasswordChangeGate,
        ActionBusinessPermission,
    ]

    http_method_names = [
        "get",
        "post",
        "patch",
        "delete",
        "head",
        "options",
    ]

    filterset_class = AnnouncementFilter

    search_fields = (
        "title",
        "content",
    )

    ordering_fields = (
        "publish_date",
        "expiry_date",
        "created_at",
        "updated_at",
        "title",
    )

    ordering = (
        "-publish_date",
        "-created_at",
    )

    response_messages = {
        "list": (
            "ANNOUNCEMENTS_RETRIEVED",
            "تم جلب الإعلانات بنجاح.",
        ),
        "retrieve": (
            "ANNOUNCEMENT_RETRIEVED",
            "تم جلب الإعلان بنجاح.",
        ),
        "create": (
            "ANNOUNCEMENT_CREATED",
            "تمت إضافة الإعلان بنجاح.",
        ),
        "partial_update": (
            "ANNOUNCEMENT_UPDATED",
            "تم تحديث الإعلان بنجاح.",
        ),
        "destroy": (
            "ANNOUNCEMENT_DELETED",
            "تم حذف الإعلان بنجاح.",
        ),
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if user.is_superuser:
            return queryset

        supervisor_scope = supervisor_academic_scope_for(user)
        if supervisor_scope.applies:
            if not supervisor_scope.scope_type:
                return queryset.none()
            if supervisor_scope.allows_all_stages:
                return queryset

            linked_grades = GradeLevel.objects.filter(announcements=OuterRef("pk"))
            linked_sections = Section.objects.filter(announcements=OuterRef("pk"))
            queryset = queryset.annotate(
                _has_grades=Exists(linked_grades),
                _has_sections=Exists(linked_sections),
                _outside_grades=Exists(
                    linked_grades.exclude(stage__in=supervisor_scope.stages)
                ),
                _outside_sections=Exists(
                    linked_sections.exclude(grade_level__stage__in=supervisor_scope.stages)
                ),
            )
            return queryset.filter(
                Q(scope=Announcement.Scope.ALL, _has_grades=False, _has_sections=False)
                | Q(scope=Announcement.Scope.GRADES, _has_grades=True,
                    _has_sections=False, _outside_grades=False)
                | Q(scope=Announcement.Scope.SECTIONS, _has_sections=True,
                    _has_grades=False, _outside_sections=False)
            )

        today = timezone.localdate()

        visible_now = (
            Q(publish_date__lte=today)
            & (
                Q(expiry_date__isnull=True)
                | Q(expiry_date__gte=today)
            )
        )

        if user.role == User.Role.TEACHER:
            active_assignments = (
                TeacherAssignment.objects
                .filter(
                    teacher=user,
                    start_date__lte=today,
                )
                .filter(
                    Q(end_date__isnull=True)
                    | Q(end_date__gte=today)
                )
            )

            section_ids = active_assignments.values_list(
                "section_id",
                flat=True,
            )

            grade_level_ids = active_assignments.values_list(
                "section__grade_level_id",
                flat=True,
            )

            allowed_scope = (
                Q(scope=Announcement.Scope.ALL)
                | Q(
                    scope=Announcement.Scope.GRADES,
                    grade_levels__id__in=grade_level_ids,
                )
                | Q(
                    scope=Announcement.Scope.SECTIONS,
                    sections__id__in=section_ids,
                )
            )

            return queryset.filter(
                visible_now,
                allowed_scope,
            ).distinct()

        if user.role == User.Role.GUARDIAN:
            active_enrollments = Enrollment.objects.filter(
                student__guardian_link__guardian=user,
                student__guardian_link__is_active=True,
                student__is_active=True,
                academic_year__status=AcademicYear.Status.ACTIVE,
            )

            section_ids = active_enrollments.values_list(
                "section_id",
                flat=True,
            )

            grade_level_ids = active_enrollments.values_list(
                "section__grade_level_id",
                flat=True,
            )

            allowed_scope = (
                Q(scope=Announcement.Scope.ALL)
                | Q(
                    scope=Announcement.Scope.GRADES,
                    grade_levels__id__in=grade_level_ids,
                )
                | Q(
                    scope=Announcement.Scope.SECTIONS,
                    sections__id__in=section_ids,
                )
            )

            return queryset.filter(
                visible_now,
                allowed_scope,
            ).distinct()

        return queryset

    def require_supervisor_targets(self, serializer):
        user = self.request.user
        scope = supervisor_academic_scope_for(user)
        if not scope.applies or scope.allows_all_stages:
            return
        if not scope.scope_type:
            raise PermissionDenied({
                "code": "SUPERVISOR_ACADEMIC_SCOPE_DENIED",
                "detail": "الإعلان خارج نطاق مراحل الموجّه.",
            })

        instance = serializer.instance
        announcement_scope = serializer.validated_data.get(
            "scope", getattr(instance, "scope", None)
        )
        grade_levels = serializer.validated_data.get("grade_levels")
        sections = serializer.validated_data.get("sections")
        if grade_levels is None:
            grade_levels = list(instance.grade_levels.all()) if instance else []
        if sections is None:
            sections = list(instance.sections.all()) if instance else []
        if (
            (announcement_scope == Announcement.Scope.GRADES and not grade_levels)
            or (announcement_scope == Announcement.Scope.SECTIONS and not sections)
            or any(not can_access_grade_level(user, grade) for grade in grade_levels)
            or any(not can_access_section(user, section) for section in sections)
        ):
            raise PermissionDenied({
                "code": "SUPERVISOR_ACADEMIC_SCOPE_DENIED",
                "detail": "الإعلان خارج نطاق مراحل الموجّه.",
            })

    @transaction.atomic
    def perform_create(self, serializer):
        self.require_supervisor_targets(serializer)
        announcement = serializer.save(
            created_by=self.request.user,
        )
        notify_announcement_published(announcement)

    def perform_update(self, serializer):
        self.require_supervisor_targets(serializer)
        serializer.save()
