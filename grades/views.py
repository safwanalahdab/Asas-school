from functools import cached_property

from django.contrib.auth import get_user_model
from django.db.models import (
    Exists,
    F,
    OuterRef,
    Q,
)
from django.utils import timezone

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema

from rest_framework import (
    mixins,
    status,
    viewsets,
)
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.filters import (
    OrderingFilter,
    SearchFilter,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import ActionBusinessPermission, PasswordChangeGate
from config.api_responses import ArabicApiResponseMixin
from teaching.models import TeacherAssignment

from .filters import AssessmentFilter
from academics.models import Section
from academics.supervisor_academic_scope import (
    filter_queryset_by_stage, is_stage_scoped_supervisor, supervisor_academic_scope_for,
)
from .supervisor_scope import (
    require_assessment, require_enrollment, require_grade_level, require_section,
)
from .models import Assessment, AssessmentSection, StudentScore
from .permissions import IsWebClientToken
from .selectors import (
    get_assessment_score_rows,
    get_student_term_results,
)
from .serializers import (
    AssessmentScoresSheetSerializer,
    AssessmentScheduleActionSerializer,
    AssessmentScheduleResultSerializer,
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
    ensure_actor_can_manage_scope,
    publish_assessment_schedule,
    publish_grade_assessments,
    publish_section_assessments,
    resolve_assessment_section,
    save_assessment_scores_bulk,
    unpublish_assessment_schedule,
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
            "grade_subject",
            "grade_subject__academic_year",
            "grade_subject__grade_level",
            "grade_subject__subject",
            "term",
            "term__academic_year",
            "created_by",
        )
        .prefetch_related(
            "assessment_sections__section",
            "assessment_sections__published_by",
            "assessment_sections__schedule_published_by",
        )
        .all()
    )

    permission_classes = [
        IsAuthenticated,
        PasswordChangeGate,
        IsWebClientToken,
        ActionBusinessPermission,
    ]

    action_permissions = {
        "list": "grades.view_assessment",
        "retrieve": "grades.view_assessment",
        "create": "grades.add_assessment",
        "partial_update": "grades.change_assessment",
        "destroy": "grades.delete_assessment",
        "create_for_grade": "grades.create_grade_wide_assessment",
        "scores_sheet": "grades.view_studentscore",
        "bulk_scores": "grades.change_studentscore",
        "publish_section": "grades.publish_grades",
        "publish_grade": "grades.publish_grades",
        "publish_schedule": "grades.publish_assessment_schedule",
        "unpublish_schedule": "grades.publish_assessment_schedule",
        "student_results": "grades.view_studentscore",
    }

    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]

    filterset_class = AssessmentFilter

    search_fields = [
        "title",
        "assessment_sections__section__name",
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
        "publish_schedule": (
            "ASSESSMENT_SCHEDULE_PUBLISHED",
            "تم نشر موعد الامتحان بنجاح.",
        ),
        "unpublish_schedule": (
            "ASSESSMENT_SCHEDULE_UNPUBLISHED",
            "تم إلغاء نشر موعد الامتحان بنجاح.",
        ),
        "student_results": (
            "STUDENT_RESULTS_RETRIEVED",
            "تم جلب نتائج الطالب بنجاح.",
        ),
    }

    def get_serializer_class(self):
        if self.action == "create":
            return CreateAssessmentSerializer

        if self.action == "partial_update":
            return UpdateAssessmentSerializer

        if self.action == "create_for_grade":
            return CreateGradeAssessmentsSerializer

        if self.action == "bulk_scores":
            return BulkAssessmentScoresSerializer

        if self.action in ("publish_schedule", "unpublish_schedule"):
            return AssessmentScheduleActionSerializer

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

        if user.role != User.Role.TEACHER:
            scope = self.supervisor_scope
            if scope.applies:
                queryset = filter_queryset_by_stage(
                    queryset, user, stage_lookup="grade_subject__grade_level__stage", scope=scope,
                )
                mismatched_links = AssessmentSection.objects.exclude(
                    section__grade_level_id=F("assessment__grade_subject__grade_level_id"),
                    section__academic_year_id=F("assessment__grade_subject__academic_year_id"),
                ).values("assessment_id")
                mismatched_scores = StudentScore.objects.exclude(
                    recorded_section__grade_level_id=F("assessment__grade_subject__grade_level_id"),
                    recorded_section__academic_year_id=F("assessment__grade_subject__academic_year_id"),
                ).values("assessment_id")
                unlinked_scores = StudentScore.objects.annotate(
                    has_link=Exists(AssessmentSection.objects.filter(
                        assessment_id=OuterRef("assessment_id"),
                        section_id=OuterRef("recorded_section_id"),
                    ))
                ).filter(has_link=False).values("assessment_id")
                queryset = (queryset.exclude(pk__in=mismatched_links)
                            .exclude(pk__in=mismatched_scores)
                            .exclude(pk__in=unlinked_scores))
                scoped_links = filter_queryset_by_stage(
                    AssessmentSection.objects.all(), user,
                    stage_lookup="section__grade_level__stage", scope=scope,
                )
                queryset = queryset.exclude(
                    pk__in=AssessmentSection.objects.exclude(pk__in=scoped_links.values("pk")).values("assessment_id")
                )
            return queryset

        if user.role == User.Role.TEACHER:
            today = timezone.localdate()

            active_assignments = (
                TeacherAssignment.objects
                .filter(
                    teacher=user,
                    section_id=OuterRef("assessment_sections__section_id"),
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
                ).distinct()
            )

        return queryset.none()

    @cached_property
    def supervisor_scope(self):
        # Views are per-request, so this loads the supervisor scope once per request.
        return supervisor_academic_scope_for(self.request.user)

    def get_object(self):
        assessment = super().get_object()
        require_assessment(self.request.user, assessment, scope=self.supervisor_scope)
        return assessment

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

        require_grade_level(request.user, serializer.validated_data["grade_subject"].grade_level)
        require_section(request.user, serializer.validated_data["section"])

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
                AssessmentSerializer,
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

        require_grade_level(request.user, serializer.validated_data["grade_subject"].grade_level)

        assessment = (
            create_assessments_for_grade(
                actor=request.user,
                **serializer.validated_data,
            )
        )

        # Reload once with the class queryset's relations and section-link
        # prefetches so the response does not lazy-load each link's section.
        assessment = self.queryset.get(pk=assessment.pk)

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
        parameters=[OpenApiParameter(name="section", type=str, location=OpenApiParameter.QUERY, required=False, description="معرّف الشعبة؛ يصبح إلزاميًا عندما يطبق التقييم على أكثر من شعبة.")],
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

        section_id = request.query_params.get("section")
        section = None
        if section_id:
            try:
                section = Section.objects.get(pk=section_id)
            except (Section.DoesNotExist, ValueError):
                from rest_framework.exceptions import ValidationError
                raise ValidationError({"section": "معرّف الشعبة غير صالح."})
        link = resolve_assessment_section(assessment=assessment, section=section)
        require_section(request.user, link.section, scope=self.supervisor_scope)
        ensure_actor_can_manage_scope(actor=request.user, section=link.section, grade_subject=assessment.grade_subject)

        records = get_assessment_score_rows(
            assessment=assessment,
            section=link.section,
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

        link = resolve_assessment_section(
            assessment=assessment,
            section=serializer.validated_data["section"],
        )
        require_section(request.user, link.section, scope=self.supervisor_scope)
        # Per-enrollment scope checks run once, in the service, on the batch
        # the serializer loaded; enrollment denials only affect supervisors,
        # whom ensure_actor_can_manage_scope never blocks, so order is unchanged.
        ensure_actor_can_manage_scope(
            actor=request.user,
            section=link.section,
            grade_subject=assessment.grade_subject,
        )

        save_assessment_scores_bulk(
            assessment=assessment,
            section=link.section,
            records=(
                serializer.validated_data[
                    "records"
                ]
            ),
            actor=request.user,
            scope=self.supervisor_scope,
        )

        records = get_assessment_score_rows(
            assessment=assessment,
            section=link.section,
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

        # One scope load per request, shared with the service's checks.
        require_section(request.user, serializer.validated_data["section"], scope=self.supervisor_scope)

        result = (
            publish_section_assessments(
                actor=request.user,
                scope=self.supervisor_scope,
                **serializer.validated_data,
            )
        )

        response_serializer = (
            PublishResultSerializer(
                {
                    **result,
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

        # One scope load per request, shared with the service's checks.
        require_grade_level(request.user, serializer.validated_data["grade_level"], scope=self.supervisor_scope)

        result = (
            publish_grade_assessments(
                actor=request.user,
                scope=self.supervisor_scope,
                **serializer.validated_data,
            )
        )

        response_serializer = (
            PublishResultSerializer(
                {
                    **result,
                }
            )
        )

        return Response(
            response_serializer.data,
        )

    def _schedule_action_scope(self, validated_data):
        assessment = validated_data["assessment"]
        if not self.get_queryset().filter(pk=assessment.pk).exists():
            raise NotFound()
        require_assessment(self.request.user, assessment)
        require_section(self.request.user, validated_data["section"])
        return assessment

    @extend_schema(
        description=(
            "ينشر موعد امتحان تقييم لشعبة محددة، ولا يتطلب وجود علامات. "
            "نشر الموعد مستقل عن نشر النتائج ويسمح بموعد امتحان مستقبلي."
        ),
        request=AssessmentScheduleActionSerializer,
        responses={
            status.HTTP_200_OK: AssessmentScheduleResultSerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(description="طلب غير صالح أو التقييم غير مرتبط بالشعبة."),
            status.HTTP_401_UNAUTHORIZED: OpenApiResponse(description="المصادقة مطلوبة."),
            status.HTTP_403_FORBIDDEN: OpenApiResponse(description="الصلاحية أو نطاق العمل غير كافيين."),
            status.HTTP_404_NOT_FOUND: OpenApiResponse(description="التقييم غير موجود ضمن نطاق المستخدم."),
        },
    )
    @action(detail=False, methods=["post"], url_path="publish-schedule")
    def publish_schedule(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self._schedule_action_scope(serializer.validated_data)
        result = publish_assessment_schedule(
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(AssessmentScheduleResultSerializer(result).data)

    @extend_schema(
        description=(
            "يلغي نشر موعد امتحان تقييم لشعبة محددة. لا يمكن إلغاء النشر "
            "بعد نشر نتائج التقييم في الشعبة."
        ),
        request=AssessmentScheduleActionSerializer,
        responses={
            status.HTTP_200_OK: AssessmentScheduleResultSerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(description="طلب غير صالح، أو نُشرت نتائج الشعبة بالفعل."),
            status.HTTP_401_UNAUTHORIZED: OpenApiResponse(description="المصادقة مطلوبة."),
            status.HTTP_403_FORBIDDEN: OpenApiResponse(description="الصلاحية أو نطاق العمل غير كافيين."),
            status.HTTP_404_NOT_FOUND: OpenApiResponse(description="التقييم غير موجود ضمن نطاق المستخدم."),
        },
    )
    @action(detail=False, methods=["post"], url_path="unpublish-schedule")
    def unpublish_schedule(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self._schedule_action_scope(serializer.validated_data)
        result = unpublish_assessment_schedule(
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(AssessmentScheduleResultSerializer(result).data)

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

        require_enrollment(request.user, enrollment)

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
            scope_user=request.user if is_stage_scoped_supervisor(request.user) else None,
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
