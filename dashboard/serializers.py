from rest_framework import serializers

from academics.models import (
    AcademicYear,
    GradeLevel,
    Section,
)


class DashboardOverviewQuerySerializer(
    serializers.Serializer,
):
    academic_year = serializers.PrimaryKeyRelatedField(
        queryset=AcademicYear.objects.all(),
        required=False,
    )

    grade_level = serializers.PrimaryKeyRelatedField(
        queryset=GradeLevel.objects.all(),
        required=False,
    )

    section = serializers.PrimaryKeyRelatedField(
        queryset=Section.objects.all(),
        required=False,
    )

    def validate(
        self,
        attrs,
    ):
        grade_level = attrs.get(
            "grade_level",
        )

        section = attrs.get(
            "section",
        )

        if (
            section is not None
            and grade_level is None
        ):
            raise serializers.ValidationError(
                {
                    "section": (
                        "يجب تحديد الصف قبل تحديد الشعبة."
                    )
                }
            )

        return attrs


class DashboardOverviewSerializer(
    serializers.Serializer,
):
    students_count = serializers.IntegerField(
        read_only=True,
    )

    active_teachers_count = serializers.IntegerField(
        read_only=True,
    )

    sections_count = serializers.IntegerField(
        read_only=True,
    )

    pending_appointments_count = serializers.IntegerField(
        read_only=True,
    )

    unanswered_guardian_requests_count = serializers.IntegerField(
        read_only=True,
    )

    total_tuition_usd = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        read_only=True,
    )

    total_discounts_usd = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        read_only=True,
    )

    total_paid_usd = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        read_only=True,
    )

    total_remaining_usd = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        read_only=True,
    )

    active_academic_year = serializers.CharField(
        allow_null=True,
        read_only=True,
    )

    current_term = serializers.CharField(
        allow_null=True,
        read_only=True,
    )

    today = serializers.DateField(
        read_only=True,
    )