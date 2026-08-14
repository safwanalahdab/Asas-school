from rest_framework import serializers

from academics.models import (
    AcademicYear,
    Term,
    GradeLevel,
    Section,
    Subject,
    GradeSubject,
)


class AcademicYearSerializer(serializers.ModelSerializer):
    name = serializers.CharField(
        read_only=True,
    )

    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    class Meta:
        model = AcademicYear

        fields = (
            "id",
            "name",
            "start_date",
            "end_date",
            "status",
            "status_display",
            "created_at",
            "updated_at",
        )

        read_only_fields = (
            "id",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        start_date = attrs.get(
            "start_date",
            getattr(self.instance, "start_date", None),
        )

        end_date = attrs.get(
            "end_date",
            getattr(self.instance, "end_date", None),
        )

        if start_date and end_date and end_date <= start_date:
            raise serializers.ValidationError(
                {
                    "end_date": (
                        "تاريخ نهاية السنة الدراسية " "يجب أن يكون بعد تاريخ البداية."
                    )
                }
            )

        if self.instance is not None and start_date and end_date:
            if self.instance.terms.filter(start_date__lt=start_date).exists():
                raise serializers.ValidationError(
                    {"start_date": "لا يمكن جعل بداية السنة بعد بداية فصل دراسي مرتبط بها."}
                )
            if self.instance.terms.filter(end_date__gt=end_date).exists():
                raise serializers.ValidationError(
                    {"end_date": "لا يمكن جعل نهاية السنة قبل نهاية فصل دراسي مرتبط بها."}
                )

        return attrs


class TermSerializer(serializers.ModelSerializer):
    number_display = serializers.CharField(
        source="get_number_display",
        read_only=True,
    )

    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    class Meta:
        model = Term

        fields = (
            "id",
            "academic_year",
            "number",
            "number_display",
            "start_date",
            "end_date",
            "status",
            "status_display",
            "created_at",
            "updated_at",
        )

        read_only_fields = (
            "id",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        academic_year = attrs.get(
            "academic_year",
            getattr(self.instance, "academic_year", None),
        )

        start_date = attrs.get(
            "start_date",
            getattr(self.instance, "start_date", None),
        )

        end_date = attrs.get(
            "end_date",
            getattr(self.instance, "end_date", None),
        )

        if start_date and end_date and end_date <= start_date:
            raise serializers.ValidationError(
                {"end_date": ("تاريخ نهاية الفصل يجب أن يكون " "بعد تاريخ البداية.")}
            )

        if academic_year and start_date:
            if start_date < academic_year.start_date:
                raise serializers.ValidationError(
                    {
                        "start_date": (
                            "بداية الفصل لا يمكن أن تكون " "قبل بداية السنة الدراسية."
                        )
                    }
                )

        if academic_year and end_date:
            if end_date > academic_year.end_date:
                raise serializers.ValidationError(
                    {
                        "end_date": (
                            "نهاية الفصل لا يمكن أن تكون " "بعد نهاية السنة الدراسية."
                        )
                    }
                )

        if academic_year and start_date and end_date:
            overlapping_terms = Term.objects.filter(
                academic_year=academic_year,
                start_date__lte=end_date,
                end_date__gte=start_date,
            )
            if self.instance is not None:
                overlapping_terms = overlapping_terms.exclude(pk=self.instance.pk)
            if overlapping_terms.exists():
                raise serializers.ValidationError(
                    {
                        "detail": (
                            "تتداخل فترة هذا الفصل الدراسي مع فصل آخر "
                            "ضمن نفس السنة الدراسية."
                        )
                    }
                )

        return attrs


class GradeLevelSerializer(serializers.ModelSerializer):
    stage_display = serializers.CharField(
        source="get_stage_display",
        read_only=True,
    )

    class Meta:
        model = GradeLevel

        fields = (
            "id",
            "stage",
            "stage_display",
            "name",
            "is_active",
            "created_at",
            "updated_at",
        )

        read_only_fields = (
            "id",
            "created_at",
            "updated_at",
        )


class SectionSerializer(serializers.ModelSerializer):
    academic_year_display = serializers.CharField(
        source="academic_year.name",
        read_only=True,
    )

    grade_level_display = serializers.CharField(
        source="grade_level.name",
        read_only=True,
    )

    class Meta:
        model = Section

        fields = (
            "id",
            "academic_year",
            "academic_year_display",
            "grade_level",
            "grade_level_display",
            "name",
            "is_active",
            "created_at",
            "updated_at",
        )

        read_only_fields = (
            "id",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        if self.instance is not None and (
            "academic_year" in attrs or "grade_level" in attrs
        ):
            used = (
                self.instance.student_enrollments.exists()
                or self.instance.teacher_assignments.exists()
            )
            if used:
                errors = {}
                if "academic_year" in attrs:
                    errors["academic_year"] = "لا يمكن تغيير سنة شعبة تحتوي على تسجيلات أو تكليفات."
                if "grade_level" in attrs:
                    errors["grade_level"] = "لا يمكن تغيير صف شعبة تحتوي على تسجيلات أو تكليفات."
                raise serializers.ValidationError(errors)
        return attrs


class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject

        fields = (
            "id",
            "name",
            "is_active",
            "created_at",
            "updated_at",
        )

        read_only_fields = (
            "id",
            "created_at",
            "updated_at",
        )


class GradeSubjectSerializer(serializers.ModelSerializer):
    academic_year_display = serializers.CharField(
        source="academic_year.name",
        read_only=True,
    )

    grade_level_display = serializers.CharField(
        source="grade_level.name",
        read_only=True,
    )

    subject_display = serializers.CharField(
        source="subject.name",
        read_only=True,
    )

    class Meta:
        model = GradeSubject

        fields = (
            "id",
            "academic_year",
            "academic_year_display",
            "grade_level",
            "grade_level_display",
            "subject",
            "subject_display",
            "is_active",
            "created_at",
            "updated_at",
        )

        read_only_fields = (
            "id",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        if self.instance is not None and self.instance.teacher_assignments.exists():
            errors = {}
            for field in ("academic_year", "grade_level", "subject"):
                if field in attrs and getattr(self.instance, f"{field}_id") != attrs[field].pk:
                    errors[field] = "لا يمكن تغيير هذا الحقل لأن مادة الخطة مرتبطة بتكليفات تعليمية."
            if errors:
                raise serializers.ValidationError(errors)
        return attrs
