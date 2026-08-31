from rest_framework import serializers

from students.models import GuardianStudent

from .models import SchoolRequest


class MobileSchoolRequestSerializer(serializers.ModelSerializer):
    request_type_display = serializers.CharField(
        source="get_request_type_display",
        read_only=True,
    )
    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )
    student_display = serializers.SerializerMethodField()

    class Meta:
        model = SchoolRequest
        fields = (
            "id",
            "request_type",
            "request_type_display",
            "details",
            "student",
            "student_display",
            "status",
            "status_display",
            "school_response",
            "answered_at",
            "created_at",
        )
        read_only_fields = (
            "id",
            "request_type_display",
            "student_display",
            "status",
            "status_display",
            "school_response",
            "answered_at",
            "created_at",
        )

    def get_student_display(self, obj):
        if obj.student is None:
            return None
        return {
            "id": str(obj.student_id),
            "name": obj.student.full_name,
        }

    def validate_student(self, student):
        if student is None:
            return None

        request = self.context["request"]
        owns_active_student = GuardianStudent.objects.filter(
            guardian=request.user,
            student=student,
            is_active=True,
            student__is_active=True,
        ).exists()
        if not owns_active_student:
            raise serializers.ValidationError(
                "الطالب المحدد غير مرتبط بحساب ولي الأمر الحالي."
            )
        return student
