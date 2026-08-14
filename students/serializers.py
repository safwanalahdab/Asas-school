from rest_framework import serializers

from accounts.models import User
from academics.models import AcademicYear, Section

from .models import (
    Enrollment,
    GuardianStudent,
    Student,
)


class StudentSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(
        read_only=True,
    )

    gender_display = serializers.CharField(
        source="get_gender_display",
        read_only=True,
    )

    class Meta:
        model = Student

        fields = (
            "id",
            "first_name",
            "last_name",
            "full_name",
            "father_name",
            "mother_name",
            "birth_date",
            "gender",
            "gender_display",
            "is_active",
            "created_at",
            "updated_at",
        )

        read_only_fields = (
            "id",
            "full_name",
            "gender_display",
            "is_active",
            "created_at",
            "updated_at",
        )


class GuardianStudentSerializer(serializers.ModelSerializer):
    guardian_display = serializers.SerializerMethodField()

    guardian_username = serializers.CharField(
        source="guardian.username",
        read_only=True,
    )

    student_display = serializers.CharField(
        source="student.full_name",
        read_only=True,
    )

    class Meta:
        model = GuardianStudent

        fields = (
            "id",
            "guardian",
            "guardian_display",
            "guardian_username",
            "student",
            "student_display",
            "is_active",
            "created_at",
            "updated_at",
        )

        read_only_fields = (
            "id",
            "guardian_display",
            "guardian_username",
            "student_display",
            "is_active",
            "created_at",
            "updated_at",
        )

    def get_guardian_display(self, obj):
        return (
            obj.guardian.get_full_name()
            or obj.guardian.username
        )

    def validate(self, attrs):
        guardian = attrs.get("guardian")
        student = attrs.get("student")

        errors = {}

        if (
            guardian
            and guardian.role != User.Role.GUARDIAN
        ):
            errors["guardian"] = (
                "المستخدم المحدد ليس ولي أمر."
            )

        if (
            student
            and GuardianStudent.objects.filter(
                student=student,
            ).exists()
        ):
            errors["student"] = (
                "الطالب مرتبط مسبقًا بحساب ولي أمر."
            )

        if errors:
            raise serializers.ValidationError(
                errors,
            )

        return attrs


class EnrollmentSerializer(serializers.ModelSerializer):
    student_display = serializers.CharField(
        source="student.full_name",
        read_only=True,
    )

    academic_year_display = serializers.CharField(
        source="academic_year.name",
        read_only=True,
    )

    section_display = serializers.CharField(
        source="section.name",
        read_only=True,
    )

    grade_level = serializers.UUIDField(
        source="section.grade_level_id",
        read_only=True,
    )

    grade_level_display = serializers.CharField(
        source="section.grade_level.name",
        read_only=True,
    )

    class Meta:
        model = Enrollment

        fields = (
            "id",
            "student",
            "student_display",
            "academic_year",
            "academic_year_display",
            "section",
            "section_display",
            "grade_level",
            "grade_level_display",
            "enrollment_date",
            "created_at",
            "updated_at",
        )

        read_only_fields = (
            "id",
            "student_display",
            "academic_year_display",
            "section_display",
            "grade_level",
            "grade_level_display",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        instance = self.instance

        if instance is not None:
            protected_fields = {
                "student": "لا يمكن تعديل الطالب بعد إنشاء التسجيل.",
                "academic_year": (
                    "لا يمكن تعديل السنة الدراسية "
                    "بعد إنشاء التسجيل."
                ),
                "section": (
                    "لا يمكن تعديل الشعبة مباشرة. "
                    "استخدم عملية نقل الطالب."
                ),
            }

            errors = {}

            for field, message in protected_fields.items():
                if field in attrs:
                    errors[field] = message

            if errors:
                raise serializers.ValidationError(
                    errors,
                )

            return attrs

        student = attrs.get("student")
        academic_year = attrs.get(
            "academic_year",
        )
        section = attrs.get("section")

        errors = {}

        if student and not student.is_active:
            errors["student"] = (
                "لا يمكن تسجيل طالب غير فعال."
            )

        if (
            academic_year
            and academic_year.status
            == AcademicYear.Status.CLOSED
        ):
            errors["academic_year"] = (
                "لا يمكن تسجيل طالب في سنة دراسية مغلقة."
            )

        if (
            academic_year
            and section
            and section.academic_year_id
            != academic_year.id
        ):
            errors["section"] = (
                "الشعبة المحددة لا تتبع "
                "السنة الدراسية المختارة."
            )

        if (
            student
            and academic_year
            and Enrollment.objects.filter(
                student=student,
                academic_year=academic_year,
            ).exists()
        ):
            errors["student"] = (
                "الطالب مسجل مسبقًا "
                "في هذه السنة الدراسية."
            )

        if errors:
            raise serializers.ValidationError(
                errors,
            )

        return attrs


class TransferEnrollmentSerializer(serializers.Serializer):
    section = serializers.PrimaryKeyRelatedField(
        queryset=Section.objects.all(),
    )