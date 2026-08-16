from django.db.models import F, Prefetch, Q

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import User
from accounts.permissions import IsWebDashboardUser
from config.api_responses import ArabicApiResponseMixin

from .filters import AttendanceRecordFilter, AttendanceSheetFilter
from .models import AttendanceRecord, AttendanceSheet
from .permissions import AttendanceRecordPermission, AttendanceSheetPermission
from .serializers import (
    AttendanceRecordSerializer,
    AttendanceSheetCreateSerializer,
    AttendanceSheetSerializer,
    BulkAttendanceUpdateSerializer,
    NormalDepartureSerializer,
)
from .services import (
    apply_normal_departure,
    bulk_update_attendance,
    create_attendance_sheet,
    update_attendance_record,
)


class AttendanceSheetViewSet(
    ArabicApiResponseMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    response_messages = {
        "create": (
            "ATTENDANCE_SHEET_CREATED",
            "تم حفظ كشف الحضور بنجاح.",
        ),
        "bulk_update": (
            "ATTENDANCE_RECORDS_UPDATED",
            "تم تصحيح سجلات الحضور بنجاح.",
        ),
        "normal_departure": (
            "ATTENDANCE_DEPARTURE_RECORDED",
            "تم تسجيل المغادرة الطبيعية بنجاح.",
        ),
    }

    permission_classes = [
        IsAuthenticated,
        IsWebDashboardUser,
        AttendanceSheetPermission,
    ]

    http_method_names = [
        "get",
        "post",
        "head",
        "options",
    ]

    queryset = AttendanceSheet.objects.select_related(
        "section",
        "section__grade_level",
        "section__academic_year",
        "created_by",
    ).all()

    filter_backends = [
        DjangoFilterBackend,
        OrderingFilter,
    ]

    filterset_class = AttendanceSheetFilter

    ordering_fields = [
        "attendance_date",
        "created_at",
    ]

    ordering = [
        "-attendance_date",
        "-created_at",
    ]

    def get_queryset(self):
        queryset = super().get_queryset()

        if self.action == "retrieve":
            records_queryset = AttendanceRecord.objects.select_related(
                "sheet",
                "sheet__section",
                "sheet__section__grade_level",
                "enrollment",
                "enrollment__student",
                "enrollment__academic_year",
                "enrollment__section",
            )

            queryset = queryset.prefetch_related(
                Prefetch(
                    "records",
                    queryset=records_queryset,
                )
            )

        user = self.request.user

        if not user.is_authenticated:
            return queryset.none()

        if user.is_superuser or user.role in {
            User.Role.SUPERVISOR,
            User.Role.SCHOOL_ADMIN,
        }:
            return queryset

        if user.role == User.Role.TEACHER:
            return queryset.filter(
                section__teacher_assignments__teacher=user,
                section__teacher_assignments__start_date__lte=F(
                    "attendance_date",
                ),
            ).filter(
                Q(
                    section__teacher_assignments__end_date__isnull=True,
                )
                | Q(
                    section__teacher_assignments__end_date__gte=F(
                        "attendance_date",
                    ),
                )
            ).distinct()

        return queryset.none()

    def get_serializer_class(self):
        if self.action == "create":
            return AttendanceSheetCreateSerializer

        return AttendanceSheetSerializer

    @extend_schema(
        request=AttendanceSheetCreateSerializer,
        responses={
            status.HTTP_201_CREATED: AttendanceSheetSerializer,
        },
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        sheet = create_attendance_sheet(
            actor=request.user,
            **serializer.validated_data,
        )

        response_serializer = AttendanceSheetSerializer(
            sheet,
            context=self.get_serializer_context(),
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        request=BulkAttendanceUpdateSerializer,
        responses={
            status.HTTP_200_OK: AttendanceSheetSerializer,
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="bulk-update",
    )
    def bulk_update(self, request, pk=None):
        sheet = self.get_object()

        serializer = BulkAttendanceUpdateSerializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        bulk_update_attendance(
            sheet=sheet,
            items=serializer.validated_data["records"],
        )

        records_queryset = AttendanceRecord.objects.select_related(
            "sheet",
            "sheet__section",
            "sheet__section__grade_level",
            "enrollment",
            "enrollment__student",
            "enrollment__academic_year",
            "enrollment__section",
        )

        sheet = AttendanceSheet.objects.prefetch_related(
            Prefetch(
                "records",
                queryset=records_queryset,
            )
        ).get(
            pk=sheet.pk,
        )

        response_serializer = AttendanceSheetSerializer(
            sheet,
        )

        return Response(
            response_serializer.data,
        )

    @extend_schema(
        request=NormalDepartureSerializer,
        responses={
            status.HTTP_200_OK: AttendanceSheetSerializer,
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="normal-departure",
    )
    def normal_departure(self, request, pk=None):
        sheet = self.get_object()

        serializer = NormalDepartureSerializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        apply_normal_departure(
            sheet=sheet,
            **serializer.validated_data,
        )

        records_queryset = AttendanceRecord.objects.select_related(
            "sheet",
            "sheet__section",
            "sheet__section__grade_level",
            "enrollment",
            "enrollment__student",
            "enrollment__academic_year",
            "enrollment__section",
        )

        sheet = AttendanceSheet.objects.prefetch_related(
            Prefetch(
                "records",
                queryset=records_queryset,
            )
        ).get(
            pk=sheet.pk,
        )

        response_serializer = AttendanceSheetSerializer(
            sheet,
        )

        return Response(
            response_serializer.data,
        )


class AttendanceRecordViewSet(
    ArabicApiResponseMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = AttendanceRecordSerializer

    permission_classes = [
        IsAuthenticated,
        IsWebDashboardUser,
        AttendanceRecordPermission,
    ]

    http_method_names = [
        "get",
        "patch",
        "head",
        "options",
    ]

    queryset = AttendanceRecord.objects.select_related(
        "sheet",
        "sheet__section",
        "sheet__section__grade_level",
        "enrollment",
        "enrollment__student",
        "enrollment__academic_year",
        "enrollment__section",
    ).all()

    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]

    filterset_class = AttendanceRecordFilter

    search_fields = [
        "enrollment__student__first_name",
        "enrollment__student__last_name",
        "enrollment__student__father_name",
        "enrollment__student__mother_name",
    ]

    ordering_fields = [
        "sheet__attendance_date",
        "created_at",
        "updated_at",
    ]

    def get_queryset(self):
        queryset = super().get_queryset()

        user = self.request.user

        if not user.is_authenticated:
            return queryset.none()

        if user.is_superuser or user.role in {
            User.Role.SUPERVISOR,
            User.Role.SCHOOL_ADMIN,
        }:
            return queryset

        if user.role == User.Role.TEACHER:
            return queryset.filter(
                sheet__section__teacher_assignments__teacher=user,
                sheet__section__teacher_assignments__start_date__lte=F(
                    "sheet__attendance_date",
                ),
            ).filter(
                Q(
                    sheet__section__teacher_assignments__end_date__isnull=True,
                )
                | Q(
                    sheet__section__teacher_assignments__end_date__gte=F(
                        "sheet__attendance_date",
                    ),
                )
            ).distinct()

        return queryset.none()

    def partial_update(self, request, *args, **kwargs):
        record = self.get_object()

        serializer = self.get_serializer(
            record,
            data=request.data,
            partial=True,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        record = update_attendance_record(
            record=record,
            data=serializer.validated_data,
        )

        response_serializer = self.get_serializer(
            record,
        )

        return Response(
            response_serializer.data,
        )
