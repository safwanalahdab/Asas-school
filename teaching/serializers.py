from django.db.models import Q
from rest_framework import serializers

from accounts.models import User
from .models import TeacherAssignment


class TeacherAssignmentSerializer(serializers.ModelSerializer):
    teacher_display = serializers.SerializerMethodField()

    academic_year_display = serializers.CharField(
        source="grade_subject.academic_year.name",
        read_only=True,
    )

    grade_level_display = serializers.CharField(
        source="grade_subject.grade_level.name",
        read_only=True,
    )

    subject_display = serializers.CharField(
        source="grade_subject.subject.name",
        read_only=True,
    )

    section_display = serializers.CharField(
        source="section.name",
        read_only=True,
    )

    class Meta:
        model = TeacherAssignment

        fields = (
            "id",

            "teacher",
            "teacher_display",

            "grade_subject",
            "academic_year_display",
            "grade_level_display",
            "subject_display",

            "section",
            "section_display",

            "start_date",
            "end_date",

            "created_at",
            "updated_at",
        )

        read_only_fields = (
            "id",
            "created_at",
            "updated_at",
        )

    def get_teacher_display(self, obj):
        return obj.teacher.get_full_name() or obj.teacher.username

    def validate(self, attrs):
        instance = self.instance

        teacher = attrs.get(
            "teacher",
            getattr(instance, "teacher", None),
        )

        grade_subject = attrs.get(
            "grade_subject",
            getattr(instance, "grade_subject", None),
        )

        section = attrs.get(
            "section",
            getattr(instance, "section", None),
        )

        start_date = attrs.get(
            "start_date",
            getattr(instance, "start_date", None),
        )

        end_date = attrs.get(
            "end_date",
            getattr(instance, "end_date", None),
        )

        errors = {}

        if teacher and teacher.role != User.Role.TEACHER:
            errors["teacher"] = (
                "يجب أن يكون المستخدم المختار معلّمًا."
            )

        if grade_subject and section:
            if (
                grade_subject.academic_year_id
                != section.academic_year_id
            ):
                errors.setdefault("section", []).append(
                    "يجب أن تكون الشعبة والمادة ضمن نفس السنة الدراسية."
                )

            if (
                grade_subject.grade_level_id
                != section.grade_level_id
            ):
                errors.setdefault("section", []).append(
                    "يجب أن تكون الشعبة والمادة تابعتين لنفس الصف."
                )

            academic_year = grade_subject.academic_year

            if start_date and not (
                academic_year.start_date
                <= start_date
                <= academic_year.end_date
            ):
                errors["start_date"] = (
                    "يجب أن يكون تاريخ بداية التكليف ضمن حدود السنة الدراسية."
                )

            if start_date and end_date and end_date < start_date:
                errors["end_date"] = (
                    "لا يمكن أن يسبق تاريخ نهاية التكليف تاريخ بدايته."
                )

            if end_date and not (
                academic_year.start_date
                <= end_date
                <= academic_year.end_date
            ):
                errors["end_date"] = (
                    "يجب أن يكون تاريخ نهاية التكليف ضمن حدود السنة الدراسية."
                )

            if start_date:
                overlapping = TeacherAssignment.objects.filter(
                    grade_subject=grade_subject,
                    section=section,
                )

                if instance:
                    overlapping = overlapping.exclude(
                        pk=instance.pk,
                    )

                overlapping = overlapping.filter(
                    Q(end_date__isnull=True)
                    | Q(end_date__gte=start_date)
                )

                if end_date:
                    overlapping = overlapping.filter(
                        start_date__lte=end_date,
                    )

                if overlapping.exists():
                    errors["start_date"] = (
                        "يوجد تكليف آخر متداخل زمنيًا "
                        "لنفس المادة والشعبة."
                    )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs