from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError

from accounts.models import User
from accounts.permissions import PasswordChangeGate
from behavior.permissions import IsWebClientToken
from config.api_responses import ArabicApiResponseMixin

from .models import StudentImportJob
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
