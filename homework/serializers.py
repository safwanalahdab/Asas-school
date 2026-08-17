from rest_framework import serializers

from .models import Homework


class HomeworkSerializer(serializers.ModelSerializer):
    teacher_display = serializers.SerializerMethodField()

    academic_year_display = serializers.CharField(
        source="teacher_assignment.grade_subject.academic_year.name",
        read_only=True,
    )

    grade_level_display = serializers.CharField(
        source="teacher_assignment.grade_subject.grade_level.name",
        read_only=True,
    )

    subject_display = serializers.CharField(
        source="teacher_assignment.grade_subject.subject.name",
        read_only=True,
    )

    section_display = serializers.CharField(
        source="teacher_assignment.section.name",
        read_only=True,
    )

    created_by_username = serializers.CharField(
        source="created_by.username",
        read_only=True,
    )

    class Meta:
        model = Homework

        fields = (
            "id",
            "teacher_assignment",
            "teacher_display",
            "academic_year_display",
            "grade_level_display",
            "subject_display",
            "section_display",
            "title",
            "description",
            "homework_date",
            "due_date",
            "attachment",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        )

        read_only_fields = (
            "id",
            "created_by",
            "created_at",
            "updated_at",
        )

    def get_teacher_display(self, obj):
        teacher = obj.teacher_assignment.teacher
        return teacher.get_full_name() or teacher.username

    def validate(self, attrs):
        instance = self.instance

        teacher_assignment = attrs.get(
            "teacher_assignment",
            getattr(instance, "teacher_assignment", None),
        )

        homework_date = attrs.get(
            "homework_date",
            getattr(instance, "homework_date", None),
        )

        due_date = attrs.get(
            "due_date",
            getattr(instance, "due_date", None),
        )

        errors = {}

        if homework_date and due_date and due_date < homework_date:
            errors["due_date"] = "لا يمكن أن يسبق موعد التسليم تاريخ الواجب."

        if errors:
            raise serializers.ValidationError(errors)

        return attrs
