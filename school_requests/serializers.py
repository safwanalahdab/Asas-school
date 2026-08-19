from django.contrib.auth import get_user_model
from rest_framework import serializers

from students.models import GuardianStudent

from .models import SchoolRequest


User = get_user_model()


class SchoolRequestSerializer(serializers.ModelSerializer):
    request_type_display = serializers.CharField(
        source="get_request_type_display",
        read_only=True,
    )

    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    guardian_username = serializers.CharField(
        source="guardian.username",
        read_only=True,
    )

    student_display = serializers.SerializerMethodField()

    handled_by_username = serializers.CharField(
        source="handled_by.username",
        read_only=True,
    )

    class Meta:
        model = SchoolRequest

        fields = (
            "id",

            "request_type",
            "request_type_display",

            "details",

            "guardian",
            "guardian_username",

            "student",
            "student_display",

            "status",
            "status_display",

            "school_response",

            "handled_by",
            "handled_by_username",

            "answered_at",

            "created_at",
            "updated_at",
        )

        read_only_fields = (
            "id",

            "guardian",

            "status",
            "school_response",
            "handled_by",
            "answered_at",

            "created_at",
            "updated_at",
        )

    def get_student_display(self, obj):
        if not obj.student:
            return None

        return {
            "id": str(obj.student.id),
            "name": obj.student.full_name,
        }

    def validate_student(self, student):
        request = self.context.get("request")

        if not request:
            return student

        user = request.user

        if user.role != User.Role.GUARDIAN:
            return student

        belongs_to_guardian = GuardianStudent.objects.filter(
            guardian=user,
            student=student,
            is_active=True,
        ).exists()

        if not belongs_to_guardian:
            raise serializers.ValidationError(
                "الطالب المحدد غير مرتبط بحساب ولي الأمر الحالي."
            )

        return student


class AnswerSchoolRequestSerializer(serializers.Serializer):
    school_response = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )