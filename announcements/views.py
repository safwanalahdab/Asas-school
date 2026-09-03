from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from accounts.permissions import PasswordChangeGate
from academics.models import AcademicYear
from config.api_responses import ArabicApiResponseMixin
from students.models import Enrollment
from teaching.models import TeacherAssignment

from .filters import AnnouncementFilter
from .models import Announcement
from .permissions import CanAccessAnnouncements
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

    permission_classes = [
        IsAuthenticated,
        PasswordChangeGate,
        CanAccessAnnouncements,
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

        if user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SUPERVISOR,
            User.Role.SECRETARIAT,
        }:
            return queryset

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

        return queryset.none()

    @transaction.atomic
    def perform_create(self, serializer):
        announcement = serializer.save(
            created_by=self.request.user,
        )
        notify_announcement_published(announcement)
