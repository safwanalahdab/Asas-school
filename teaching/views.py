from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import User
from accounts.permissions import IsWebDashboardUser

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter, SearchFilter
from .filters import TeacherAssignmentFilter

from .models import TeacherAssignment
from .permissions import TeachingAssignmentPermission
from .serializers import TeacherAssignmentSerializer


class TeacherAssignmentViewSet(viewsets.ModelViewSet):
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

        serializer.save()

        return Response(
            {
                "code": "teacher_assignment_ended",
                "detail": "تم إنهاء تكليف المعلّم بنجاح.",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )
