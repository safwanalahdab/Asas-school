from django.db.models.deletion import ProtectedError
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from config.api_responses import ArabicApiResponseMixin
from audit_logs.mixins import AuditModelViewSetMixin

from .permissions import AcademicManagementPermission

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter, SearchFilter

from .models import (
    AcademicYear,
    Term,
    GradeLevel,
    Section,
    Subject,
    GradeSubject,
)

from .serializers import (
    AcademicYearSerializer,
    TermSerializer,
    GradeLevelSerializer,
    SectionSerializer,
    SubjectSerializer,
    GradeSubjectSerializer,
)

ACADEMIC_HTTP_METHODS = (
    "get",
    "post",
    "patch",
    "delete",
    "head",
    "options",
)


class AcademicYearViewSet(ArabicApiResponseMixin, AuditModelViewSetMixin, viewsets.ModelViewSet):
    response_messages = {
        "list": ("ACADEMIC_YEARS_RETRIEVED", "تم جلب قائمة السنوات الدراسية بنجاح."),
        "retrieve": ("ACADEMIC_YEAR_RETRIEVED", "تم جلب السنة الدراسية بنجاح."),
        "create": ("ACADEMIC_YEAR_CREATED", "تمت إضافة السنة الدراسية بنجاح."),
        "partial_update": ("ACADEMIC_YEAR_UPDATED", "تم تحديث السنة الدراسية بنجاح."),
        "destroy": ("ACADEMIC_YEAR_DELETED", "تم حذف السنة الدراسية بنجاح."),
    }
    queryset = AcademicYear.objects.all()
    serializer_class = AcademicYearSerializer
    permission_classes = [
        AcademicManagementPermission,
    ]
    http_method_names = ACADEMIC_HTTP_METHODS

    filter_backends = [
        DjangoFilterBackend,
        OrderingFilter,
    ]

    filterset_fields = [
        "status",
    ]

    ordering_fields = [
        "start_date",
        "end_date",
        "created_at",
    ]

    ordering = [
        "-start_date",
    ]

    def destroy(self, request, *args, **kwargs):
        academic_year = self.get_object()

        try:
            return super().destroy(request, *args, **kwargs)

        except ProtectedError:
            raise ValidationError(
                {
                    "code": "ACADEMIC_YEAR_DELETE_BLOCKED",
                    "detail": (
                        "لا يمكن حذف السنة الدراسية لوجود فصول أو شعب أو تسجيلات أو بيانات أكاديمية مرتبطة بها."
                    )
                }
            )


class TermViewSet(ArabicApiResponseMixin, AuditModelViewSetMixin, viewsets.ModelViewSet):
    response_messages = {
        "list": ("TERMS_RETRIEVED", "تم جلب قائمة الفصول الدراسية بنجاح."),
        "retrieve": ("TERM_RETRIEVED", "تم جلب الفصل الدراسي بنجاح."),
        "create": ("TERM_CREATED", "تمت إضافة الفصل الدراسي بنجاح."),
        "partial_update": ("TERM_UPDATED", "تم تحديث الفصل الدراسي بنجاح."),
        "destroy": ("TERM_DELETED", "تم حذف الفصل الدراسي بنجاح."),
    }
    queryset = Term.objects.select_related(
        "academic_year",
    ).all()

    serializer_class = TermSerializer
    permission_classes = [
        AcademicManagementPermission,
    ]
    http_method_names = ACADEMIC_HTTP_METHODS

    filter_backends = [
        DjangoFilterBackend,
        OrderingFilter,
    ]

    filterset_fields = [
        "academic_year",
        "number",
        "status",
    ]

    ordering_fields = [
        "number",
        "start_date",
        "end_date",
        "created_at",
    ]

    ordering = [
        "number",
    ]

    def destroy(self, request, *args, **kwargs):
        term = self.get_object()

        try:
            return super().destroy(
                request,
                *args,
                **kwargs,
            )

        except ProtectedError:
            raise ValidationError(
                {
                    "code": "TERM_DELETE_BLOCKED",
                    "detail": (
                        "لا يمكن حذف الفصل الدراسي لأنه " "مرتبط ببيانات أكاديمية."
                    )
                }
            )


class GradeLevelViewSet(ArabicApiResponseMixin, AuditModelViewSetMixin, viewsets.ModelViewSet):
    response_messages = {
        "list": ("GRADE_LEVELS_RETRIEVED", "تم جلب قائمة الصفوف الدراسية بنجاح."),
        "retrieve": ("GRADE_LEVEL_RETRIEVED", "تم جلب الصف الدراسي بنجاح."),
        "create": ("GRADE_LEVEL_CREATED", "تمت إضافة الصف الدراسي بنجاح."),
        "partial_update": ("GRADE_LEVEL_UPDATED", "تم تحديث الصف الدراسي بنجاح."),
        "destroy": ("GRADE_LEVEL_DELETED", "تم حذف الصف الدراسي بنجاح."),
    }
    queryset = GradeLevel.objects.all()

    serializer_class = GradeLevelSerializer
    permission_classes = [
        AcademicManagementPermission,
    ]
    http_method_names = ACADEMIC_HTTP_METHODS

    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]

    filterset_fields = [
        "stage",
        "is_active",
    ]

    search_fields = [
        "name",
    ]

    ordering_fields = [
        "name",
        "stage",
        "created_at",
    ]

    ordering = [
        "stage",
        "name",
    ]

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(
                request,
                *args,
                **kwargs,
            )

        except ProtectedError:
            raise ValidationError(
                {"code": "GRADE_LEVEL_DELETE_BLOCKED", "detail": "لا يمكن حذف الصف لوجود شعب أو خطط أو بيانات دراسية مرتبطة به."}
            )


class SectionViewSet(ArabicApiResponseMixin, AuditModelViewSetMixin, viewsets.ModelViewSet):
    response_messages = {
        "list": ("SECTIONS_RETRIEVED", "تم جلب قائمة الشعب بنجاح."),
        "retrieve": ("SECTION_RETRIEVED", "تم جلب الشعبة بنجاح."),
        "create": ("SECTION_CREATED", "تمت إضافة الشعبة بنجاح."),
        "partial_update": ("SECTION_UPDATED", "تم تحديث الشعبة بنجاح."),
        "destroy": ("SECTION_DELETED", "تم حذف الشعبة بنجاح."),
    }
    queryset = Section.objects.select_related(
        "academic_year",
        "grade_level",
    ).all()

    serializer_class = SectionSerializer
    permission_classes = [
        AcademicManagementPermission,
    ]
    http_method_names = ACADEMIC_HTTP_METHODS

    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]

    filterset_fields = [
        "academic_year",
        "grade_level",
        "is_active",
    ]

    search_fields = [
        "name",
        "grade_level__name",
    ]

    ordering_fields = [
        "name",
        "created_at",
    ]

    ordering = [
        "name",
    ]

    def destroy(self, request, *args, **kwargs):
        section = self.get_object()

        try:
            return super().destroy(
                request,
                *args,
                **kwargs,
            )

        except ProtectedError:
            raise ValidationError(
                {"code": "SECTION_DELETE_BLOCKED", "detail": "لا يمكن حذف الشعبة لأنها تحتوي على طلاب أو تكليفات تعليمية مرتبطة بها."}
            )


class SubjectViewSet(ArabicApiResponseMixin, AuditModelViewSetMixin, viewsets.ModelViewSet):
    response_messages = {
        "list": ("SUBJECTS_RETRIEVED", "تم جلب قائمة المواد بنجاح."),
        "retrieve": ("SUBJECT_RETRIEVED", "تم جلب المادة بنجاح."),
        "create": ("SUBJECT_CREATED", "تمت إضافة المادة بنجاح."),
        "partial_update": ("SUBJECT_UPDATED", "تم تحديث المادة بنجاح."),
        "destroy": ("SUBJECT_DELETED", "تم حذف المادة بنجاح."),
    }
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer
    permission_classes = [
        AcademicManagementPermission,
    ]
    http_method_names = ACADEMIC_HTTP_METHODS

    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]

    filterset_fields = [
        "is_active",
    ]

    search_fields = [
        "name",
    ]

    ordering_fields = [
        "name",
        "created_at",
    ]

    ordering = [
        "name",
    ]

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(
                request,
                *args,
                **kwargs,
            )

        except ProtectedError:
            raise ValidationError(
                {
                    "code": "SUBJECT_DELETE_BLOCKED",
                    "detail": (
                        "لا يمكن حذف المادة لأنها "
                        "مرتبطة بخطة دراسية أو بيانات أكاديمية."
                    )
                }
            )


class GradeSubjectViewSet(ArabicApiResponseMixin, AuditModelViewSetMixin, viewsets.ModelViewSet):
    response_messages = {
        "list": ("GRADE_SUBJECTS_RETRIEVED", "تم جلب الخطة الدراسية بنجاح."),
        "retrieve": ("GRADE_SUBJECT_RETRIEVED", "تم جلب مادة الخطة الدراسية بنجاح."),
        "create": ("GRADE_SUBJECT_CREATED", "تمت إضافة المادة إلى الخطة الدراسية بنجاح."),
        "partial_update": ("GRADE_SUBJECT_UPDATED", "تم تحديث مادة الخطة الدراسية بنجاح."),
        "destroy": ("GRADE_SUBJECT_DELETED", "تم حذف المادة من الخطة الدراسية بنجاح."),
    }
    queryset = GradeSubject.objects.select_related(
        "academic_year",
        "grade_level",
        "subject",
    ).all()

    serializer_class = GradeSubjectSerializer
    permission_classes = [
        AcademicManagementPermission,
    ]
    http_method_names = ACADEMIC_HTTP_METHODS

    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]

    filterset_fields = [
        "academic_year",
        "grade_level",
        "subject",
        "is_active",
    ]

    search_fields = [
        "subject__name",
        "grade_level__name",
    ]

    ordering_fields = [
        "created_at",
    ]

    ordering = [
        "-created_at",
    ]

    def destroy(self, request, *args, **kwargs):
        grade_subject = self.get_object()

        try:
            return super().destroy(
                request,
                *args,
                **kwargs,
            )

        except ProtectedError:
            raise ValidationError(
                {
                    "code": "GRADE_SUBJECT_DELETE_BLOCKED",
                    "detail": (
                        "لا يمكن حذف المادة من الخطة " "لأنها مرتبطة ببيانات أكاديمية."
                    )
                }
            )
