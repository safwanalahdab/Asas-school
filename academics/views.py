from django.db.models.deletion import ProtectedError
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

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


class AcademicYearViewSet(viewsets.ModelViewSet):
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

        if academic_year.status != AcademicYear.Status.DRAFT:
            raise ValidationError(
                {"detail": ("لا يمكن حذف السنة الدراسية " "بعد تفعيلها أو إغلاقها.")}
            )

        try:
            return super().destroy(request, *args, **kwargs)

        except ProtectedError:
            raise ValidationError(
                {
                    "detail": (
                        "لا يمكن حذف السنة الدراسية لأنها " "مرتبطة ببيانات أكاديمية."
                    )
                }
            )


class TermViewSet(viewsets.ModelViewSet):
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

        if term.status != Term.Status.DRAFT:
            raise ValidationError(
                {"detail": ("لا يمكن حذف الفصل الدراسي " "بعد تفعيله أو إغلاقه.")}
            )

        if term.academic_year.status != AcademicYear.Status.DRAFT:
            raise ValidationError(
                {"detail": ("لا يمكن حذف فصل تابع لسنة " "دراسية مفعلة أو مغلقة.")}
            )

        try:
            return super().destroy(
                request,
                *args,
                **kwargs,
            )

        except ProtectedError:
            raise ValidationError(
                {
                    "detail": (
                        "لا يمكن حذف الفصل الدراسي لأنه " "مرتبط ببيانات أكاديمية."
                    )
                }
            )


class GradeLevelViewSet(viewsets.ModelViewSet):
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
                {"detail": ("لا يمكن حذف الصف لأنه مرتبط " "ببيانات أكاديمية.")}
            )


class SectionViewSet(viewsets.ModelViewSet):
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

        if section.academic_year.status == AcademicYear.Status.CLOSED:
            raise ValidationError(
                {"detail": ("لا يمكن حذف شعبة تابعة " "لسنة دراسية مغلقة.")}
            )

        try:
            return super().destroy(
                request,
                *args,
                **kwargs,
            )

        except ProtectedError:
            raise ValidationError(
                {"detail": ("لا يمكن حذف الشعبة لأنها " "مرتبطة ببيانات أكاديمية.")}
            )


class SubjectViewSet(viewsets.ModelViewSet):
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
                    "detail": (
                        "لا يمكن حذف المادة لأنها "
                        "مرتبطة بخطة دراسية أو بيانات أكاديمية."
                    )
                }
            )


class GradeSubjectViewSet(viewsets.ModelViewSet):
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

        if grade_subject.academic_year.status == AcademicYear.Status.CLOSED:
            raise ValidationError(
                {"detail": ("لا يمكن حذف مادة من خطة " "سنة دراسية مغلقة.")}
            )

        try:
            return super().destroy(
                request,
                *args,
                **kwargs,
            )

        except ProtectedError:
            raise ValidationError(
                {
                    "detail": (
                        "لا يمكن حذف المادة من الخطة " "لأنها مرتبطة ببيانات أكاديمية."
                    )
                }
            )
