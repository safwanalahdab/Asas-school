from drf_spectacular.utils import extend_schema, extend_schema_field
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError

from accounts.models import User
from accounts.permissions import PasswordChangeGate
from behavior.permissions import IsWebClientToken
from config.api_responses import ArabicApiResponseMixin

from .models import StudentImportJob, StudentImportRow
from .student_import_batch_service import (
    StudentImportBatchError,
    process_next_batch,
)
from .student_import_job_service import create_student_import_job


class StudentImportUploadSerializer(serializers.Serializer):
    file = serializers.FileField(
        required=True,
        allow_empty_file=False,
        error_messages={
            "required": "ملف Excel مطلوب.",
            "empty": "ملف Excel المرفوع فارغ.",
        },
    )


class StudentImportJobSummarySerializer(serializers.ModelSerializer):
    ready_rows = serializers.IntegerField(source="valid_rows", read_only=True)
    review_required_rows = serializers.IntegerField(
        source="review_rows",
        read_only=True,
    )

    class Meta:
        model = StudentImportJob
        fields = (
            "id",
            "status",
            "total_rows",
            "ready_rows",
            "invalid_rows",
            "review_required_rows",
            "succeeded_rows",
            "failed_rows",
            "created_at",
        )
        read_only_fields = fields


class StudentImportRowSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentImportRow
        fields = (
            "id",
            "row_number",
            "status",
            "validation_errors",
        )
        read_only_fields = fields


class StudentImportRowFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=StudentImportRow.Status.choices,
        required=False,
    )


class StudentImportBatchSummarySerializer(serializers.Serializer):
    claimed_rows = serializers.IntegerField(read_only=True)
    succeeded_rows = serializers.IntegerField(read_only=True)
    failed_rows = serializers.IntegerField(read_only=True)


class StudentImportProcessResponseSerializer(StudentImportJobSummarySerializer):
    batch = serializers.SerializerMethodField()

    class Meta(StudentImportJobSummarySerializer.Meta):
        fields = (*StudentImportJobSummarySerializer.Meta.fields, "batch")
        read_only_fields = fields

    @extend_schema_field(StudentImportBatchSummarySerializer)
    def get_batch(self, obj):
        result = self.context["batch_result"]
        return {
            "claimed_rows": result.claimed_rows,
            "succeeded_rows": sum(
                row.status == StudentImportRow.Status.SUCCEEDED
                for row in result.rows
            ),
            "failed_rows": sum(
                row.status == StudentImportRow.Status.FAILED
                for row in result.rows
            ),
        }


class CanUploadStudentImport(BasePermission):
    message = {
        "code": "STUDENT_IMPORT_UPLOAD_DENIED",
        "detail": "ليس لديك صلاحية لاستيراد الطلاب.",
    }

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and (
                user.is_superuser
                or user.role
                in {
                    User.Role.SCHOOL_ADMIN,
                    User.Role.SECRETARIAT,
                }
            )
        )


class StudentImportUploadView(ArabicApiResponseMixin, APIView):
    permission_classes = [
        IsAuthenticated,
        PasswordChangeGate,
        IsWebClientToken,
        CanUploadStudentImport,
    ]
    parser_classes = [MultiPartParser]
    http_method_names = ["post", "head", "options"]
    response_messages = {
        "post": (
            "STUDENT_IMPORT_VALIDATED",
            "تم فحص ملف استيراد الطلاب وحفظ النتيجة بنجاح.",
        ),
    }

    @extend_schema(
        request=StudentImportUploadSerializer,
        responses={status.HTTP_201_CREATED: StudentImportJobSummarySerializer},
    )
    def post(self, request):
        request_serializer = StudentImportUploadSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        uploaded_file = request_serializer.validated_data["file"]

        result = create_student_import_job(
            uploaded_file=uploaded_file,
            created_by=request.user,
        )
        if not result.created:
            raise ValidationError(
                {
                    "code": "STUDENT_IMPORT_FILE_INVALID",
                    "detail": "تعذر قبول ملف استيراد الطلاب.",
                    "file": [error.to_dict() for error in result.file_errors],
                }
            )

        response_serializer = StudentImportJobSummarySerializer(result.job)
        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )


class StudentImportJobDetailView(
    ArabicApiResponseMixin,
    generics.RetrieveAPIView,
):
    queryset = StudentImportJob.objects.all()
    serializer_class = StudentImportJobSummarySerializer
    permission_classes = [
        IsAuthenticated,
        PasswordChangeGate,
        IsWebClientToken,
        CanUploadStudentImport,
    ]
    lookup_url_kwarg = "job_id"
    response_messages = {
        "get": (
            "STUDENT_IMPORT_RETRIEVED",
            "تم جلب ملخص استيراد الطلاب بنجاح.",
        ),
    }


class StudentImportJobRowsView(
    ArabicApiResponseMixin,
    generics.ListAPIView,
):
    serializer_class = StudentImportRowSummarySerializer
    permission_classes = [
        IsAuthenticated,
        PasswordChangeGate,
        IsWebClientToken,
        CanUploadStudentImport,
    ]
    response_messages = {
        "get": (
            "STUDENT_IMPORT_ROWS_RETRIEVED",
            "تم جلب صفوف استيراد الطلاب بنجاح.",
        ),
    }

    @extend_schema(parameters=[StudentImportRowFilterSerializer])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        job = get_object_or_404(
            StudentImportJob.objects.all(),
            pk=self.kwargs["job_id"],
        )
        filter_serializer = StudentImportRowFilterSerializer(
            data=self.request.query_params,
        )
        filter_serializer.is_valid(raise_exception=True)

        queryset = job.rows.order_by("row_number")
        row_status = filter_serializer.validated_data.get("status")
        if row_status:
            queryset = queryset.filter(status=row_status)
        return queryset


class StudentImportProcessView(ArabicApiResponseMixin, APIView):
    permission_classes = [
        IsAuthenticated,
        PasswordChangeGate,
        IsWebClientToken,
        CanUploadStudentImport,
    ]
    http_method_names = ["post", "head", "options"]
    response_messages = {
        "post": (
            "STUDENT_IMPORT_BATCH_PROCESSED",
            "تمت معالجة الدفعة التالية من استيراد الطلاب.",
        ),
    }

    @extend_schema(
        request=None,
        responses={status.HTTP_200_OK: StudentImportProcessResponseSerializer},
    )
    def post(self, request, job_id):
        job = get_object_or_404(StudentImportJob.objects.all(), pk=job_id)
        try:
            result = process_next_batch(job=job, actor=request.user)
        except StudentImportBatchError as error:
            raise ValidationError(
                {
                    "code": error.code,
                    "detail": error.detail,
                }
            ) from error

        response_serializer = StudentImportProcessResponseSerializer(
            result.job,
            context={"batch_result": result},
        )
        return Response(response_serializer.data, status=status.HTTP_200_OK)
