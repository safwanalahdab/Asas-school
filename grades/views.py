from django.contrib.auth import get_user_model
from django.db.models import (
    Exists,
    OuterRef,
    Q,
)
from django.utils import timezone

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema

from rest_framework import (
    mixins,
    status,
    viewsets,
)
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.filters import (
    OrderingFilter,
    SearchFilter,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import IsWebDashboardUser
from config.api_responses import ArabicApiResponseMixin
from teaching.models import TeacherAssignment

from .filters import AssessmentFilter
from .models import Assessment
from .permissions import (
    CanAccessGrades,
    CanCreateGradeWideAssessment,
    CanPublishGrades,
)
from .selectors import (
    get_assessment_score_rows,
    get_student_term_results,
)
from .serializers import (
    AssessmentScoresSheetSerializer,
    AssessmentSerializer,
    BulkAssessmentScoresSerializer,
    CreateAssessmentSerializer,
    CreateGradeAssessmentsSerializer,
    PublishGradeSerializer,
    PublishResultSerializer,
    PublishSectionSerializer,
    StudentResultsQuerySerializer,
    StudentTermResultsSerializer,
    UpdateAssessmentSerializer,
)
from .services import (
    create_assessment,
    create_assessments_for_grade,
    delete_assessment,
    publish_grade_assessments,
    publish_section_assessments,
    save_assessment_scores_bulk,
    update_assessment,
)


User = get_user_model()


class AssessmentViewSet(
    ArabicApiResponseMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = (
        Assessment.objects
        .select_related(
            "section",
            "section__academic_year",
            "section__grade_level",
            "grade_subject",
            "grade_subject__academic_year",
            "grade_subject__grade_level",
            "grade_subject__subject",
            "term",
            "term__academic_year",
            "created_by",
            "published_by",
        )
        .all()
    )

    permission_classes = [
        IsAuthenticated,
        IsWebDashboardUser,
        CanAccessGrades,
    ]

    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]

    filterset_class = AssessmentFilter

    search_fields = [
        "title",
        "section__name",
        "grade_subject__subject__name",
    ]

    ordering_fields = [
        "assessment_date",
        "created_at",
        "updated_at",
        "max_score",
    ]

    ordering = [
        "-assessment_date",
        "-created_at",
    ]

    http_method_names = [
        "get",
        "post",
        "patch",
        "delete",
        "head",
        "options",
    ]

    response_messages = {
        "list": (
            "ASSESSMENTS_RETRIEVED",
            "تم جلب التقييمات بنجاح.",
        ),
        "retrieve": (
            "ASSESSMENT_RETRIEVED",
            "تم جلب التقييم بنجاح.",
        ),
        "create": (
            "ASSESSMENT_CREATED",
            "تم إنشاء التقييم بنجاح.",
        ),
        "partial_update": (
            "ASSESSMENT_UPDATED",
            "تم تعديل التقييم بنجاح.",
        ),
        "destroy": (
            "ASSESSMENT_DELETED",
            "تم حذف التقييم بنجاح.",
        ),
        "create_for_grade": (
            "GRADE_ASSESSMENTS_CREATED",
            "تم إنشاء التقييم لجميع شعب الصف بنجاح.",
        ),
        "scores_sheet": (
            "ASSESSMENT_SCORES_RETRIEVED",
            "تم جلب كشف علامات التقييم بنجاح.",
        ),
        "bulk_scores": (
            "ASSESSMENT_SCORES_UPDATED",
            "تم حفظ علامات الطلاب بنجاح.",
        ),
        "publish_section": (
            "SECTION_RESULTS_PUBLISHED",
            "تم اعتماد ونشر نتائج الشعبة بنجاح.",
        ),
        "publish_grade": (
            "GRADE_RESULTS_PUBLISHED",
            "تم اعتماد ونشر نتائج الصف بنجاح.",
        ),
        "student_results": (
            "STUDENT_RESULTS_RETRIEVED",
            "تم جلب نتائج الطالب بنجاح.",
        ),
    }

    def get_permissions(self):
        permission_classes = list(
            self.permission_classes
        )

        action_name = getattr(
            self,
            "action",
            None,
        )

        if action_name in {
            "publish_section",
            "publish_grade",
        }:
            permission_classes.append(
                CanPublishGrades
            )

        if action_name == "create_for_grade":
            permission_classes.append(
                CanCreateGradeWideAssessment
            )

        return [
            permission()
            for permission in permission_classes
        ]

    def get_serializer_class(self):
        if self.action == "create":
            return CreateAssessmentSerializer

        if self.action == "partial_update":
            return UpdateAssessmentSerializer

        if self.action == "create_for_grade":
            return CreateGradeAssessmentsSerializer

        if self.action == "bulk_scores":
            return BulkAssessmentScoresSerializer

        if self.action == "publish_section":
            return PublishSectionSerializer

        if self.action == "publish_grade":
            return PublishGradeSerializer

        if self.action == "student_results":
            return StudentResultsQuerySerializer

        return AssessmentSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        user = self.request.user

        if not user.is_authenticated:
            return queryset.none()

        if user.is_superuser:
            return queryset

        if user.role in {
            User.Role.SCHOOL_ADMIN,
            User.Role.SUPERVISOR,
        }:
            return queryset

        if user.role == User.Role.TEACHER:
            today = timezone.localdate()

            active_assignments = (
                TeacherAssignment.objects
                .filter(
                    teacher=user,
                    section_id=OuterRef(
                        "section_id"
                    ),
                    grade_subject_id=OuterRef(
                        "grade_subject_id"
                    ),
                    start_date__lte=today,
                )
                .filter(
                    Q(
                        end_date__isnull=True,
                    )
                    | Q(
                        end_date__gte=today,
                    )
                )
            )

            return (
                queryset
                .annotate(
                    teacher_has_access=Exists(
                        active_assignments
                    )
                )
                .filter(
                    teacher_has_access=True,
                )
            )

        return queryset.none()

    @extend_schema(
        request=CreateAssessmentSerializer,
        responses={
            status.HTTP_201_CREATED:
                AssessmentSerializer,
        },
    )
    def create(
        self,
        request,
        *args,
        **kwargs,
    ):
        serializer = self.get_serializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        assessment = create_assessment(
            actor=request.user,
            **serializer.validated_data,
        )

        response_serializer = (
            AssessmentSerializer(
                assessment,
                context=(
                    self.get_serializer_context()
                ),
            )
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        request=UpdateAssessmentSerializer,
        responses={
            status.HTTP_200_OK:
                AssessmentSerializer,
        },
    )
    def partial_update(
        self,
        request,
        *args,
        **kwargs,
    ):
        assessment = self.get_object()

        serializer = self.get_serializer(
            assessment,
            data=request.data,
            partial=True,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        validated_data = dict(
            serializer.validated_data
        )

        allow_duplicate = validated_data.pop(
            "allow_duplicate",
            False,
        )

        assessment = update_assessment(
            assessment=assessment,
            actor=request.user,
            allow_duplicate=allow_duplicate,
            **validated_data,
        )

        response_serializer = (
            AssessmentSerializer(
                assessment,
                context=(
                    self.get_serializer_context()
                ),
            )
        )

        return Response(
            response_serializer.data,
        )

    @extend_schema(
        responses={
            status.HTTP_204_NO_CONTENT: None,
        },
    )
    def destroy(
        self,
        request,
        *args,
        **kwargs,
    ):
        assessment = self.get_object()

        delete_assessment(
            assessment=assessment,
            actor=request.user,
        )

        return Response(
            status=status.HTTP_204_NO_CONTENT,
        )

    @extend_schema(
        request=CreateGradeAssessmentsSerializer,
        responses={
            status.HTTP_201_CREATED:
                AssessmentSerializer(
                    many=True
                ),
        },
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="create-for-grade",
    )
    def create_for_grade(
        self,
        request,
    ):
        serializer = self.get_serializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        assessments = (
            create_assessments_for_grade(
                actor=request.user,
                **serializer.validated_data,
            )
        )

        response_serializer = (
            AssessmentSerializer(
                assessments,
                many=True,
                context=(
                    self.get_serializer_context()
                ),
            )
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        responses={
            status.HTTP_200_OK:
                AssessmentScoresSheetSerializer,
        },
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="scores",
    )
    def scores_sheet(
        self,
        request,
        pk=None,
    ):
        assessment = self.get_object()

        records = get_assessment_score_rows(
            assessment=assessment,
        )

        response_serializer = (
            AssessmentScoresSheetSerializer(
                {
                    "assessment": assessment,
                    "records": records,
                },
                context=(
                    self.get_serializer_context()
                ),
            )
        )

        return Response(
            response_serializer.data,
        )

    @extend_schema(
        request=BulkAssessmentScoresSerializer,
        responses={
            status.HTTP_200_OK:
                AssessmentScoresSheetSerializer,
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="scores/bulk",
    )
    def bulk_scores(
        self,
        request,
        pk=None,
    ):
        assessment = self.get_object()

        serializer = self.get_serializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        save_assessment_scores_bulk(
            assessment=assessment,
            records=(
                serializer.validated_data[
                    "records"
                ]
            ),
            actor=request.user,
        )

        records = get_assessment_score_rows(
            assessment=assessment,
        )

        response_serializer = (
            AssessmentScoresSheetSerializer(
                {
                    "assessment": assessment,
                    "records": records,
                },
                context=(
                    self.get_serializer_context()
                ),
            )
        )

        return Response(
            response_serializer.data,
        )

    @extend_schema(
        request=PublishSectionSerializer,
        responses={
            status.HTTP_200_OK:
                PublishResultSerializer,
        },
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="publish-section",
    )
    def publish_section(
        self,
        request,
    ):
        serializer = self.get_serializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        published_count = (
            publish_section_assessments(
                actor=request.user,
                **serializer.validated_data,
            )
        )

        response_serializer = (
            PublishResultSerializer(
                {
                    "published_count":
                        published_count,
                }
            )
        )

        return Response(
            response_serializer.data,
        )

    @extend_schema(
        request=PublishGradeSerializer,
        responses={
            status.HTTP_200_OK:
                PublishResultSerializer,
        },
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="publish-grade",
    )
    def publish_grade(
        self,
        request,
    ):
        serializer = self.get_serializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        published_count = (
            publish_grade_assessments(
                actor=request.user,
                **serializer.validated_data,
            )
        )

        response_serializer = (
            PublishResultSerializer(
                {
                    "published_count":
                        published_count,
                }
            )
        )

        return Response(
            response_serializer.data,
        )

    @extend_schema(
        parameters=[
            StudentResultsQuerySerializer,
        ],
        responses={
            status.HTTP_200_OK:
                StudentTermResultsSerializer,
        },
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="student-results",
    )
    def student_results(
        self,
        request,
    ):
        query_serializer = (
            StudentResultsQuerySerializer(
                data=request.query_params,
            )
        )

        query_serializer.is_valid(
            raise_exception=True,
        )

        enrollment = (
            query_serializer
            .validated_data[
                "enrollment"
            ]
        )

        term = (
            query_serializer
            .validated_data[
                "term"
            ]
        )

        subjects = get_student_term_results(
            enrollment=enrollment,
            term=term,
            published_only=False,
        )

        user = request.user

        if (
            not user.is_superuser
            and user.role
            == User.Role.TEACHER
        ):
            today = timezone.localdate()

            allowed_grade_subject_ids = set(
                TeacherAssignment.objects
                .filter(
                    teacher=user,
                    section=enrollment.section,
                    start_date__lte=today,
                )
                .filter(
                    Q(
                        end_date__isnull=True,
                    )
                    | Q(
                        end_date__gte=today,
                    )
                )
                .values_list(
                    "grade_subject_id",
                    flat=True,
                )
            )

            if not allowed_grade_subject_ids:
                raise PermissionDenied(
                    {
                        "code": (
                            "GRADE_RESULTS_ACCESS_DENIED"
                        ),
                        "detail": (
                            "لا يمكنك عرض نتائج "
                            "طالب من شعبة غير "
                            "مكلّف بها."
                        ),
                    }
                )

            subjects = [
                subject_result
                for subject_result in subjects
                if (
                    subject_result[
                        "grade_subject"
                    ]
                    in allowed_grade_subject_ids
                )
            ]

        response_data = {
            "enrollment": enrollment.id,
            "student": enrollment.student_id,
            "student_display": (
                enrollment.student.full_name
            ),
            "term": term.id,
            "term_display": (
                term.get_number_display()
            ),
            "subjects": subjects,
        }

        response_serializer = (
            StudentTermResultsSerializer(
                response_data
            )
        )

        return Response(
            response_serializer.data,
        )