from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from academics.models import Subject
from homework.models import Homework


class MobileHomeworkFilterSerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    subject = serializers.UUIDField(required=False)

    def validate(self, attrs):
        date_from = attrs.get("date_from")
        date_to = attrs.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise serializers.ValidationError({
                "date_to": "يجب أن يكون تاريخ النهاية مساويًا لتاريخ البداية أو بعده."
            })
        return attrs


class MobileHomeworkSubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ("id", "name")
        read_only_fields = fields


class MobileHomeworkTeacherSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    full_name = serializers.CharField(read_only=True)


class MobileHomeworkSectionSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)


class MobileHomeworkSerializer(serializers.ModelSerializer):
    subject = MobileHomeworkSubjectSerializer(
        source="teacher_assignment.grade_subject.subject", read_only=True
    )
    teacher = serializers.SerializerMethodField()
    section = MobileHomeworkSectionSerializer(
        source="teacher_assignment.section", read_only=True
    )

    class Meta:
        model = Homework
        fields = (
            "id", "title", "description", "homework_date", "due_date",
            "attachment", "subject", "teacher", "section", "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(MobileHomeworkTeacherSerializer)
    def get_teacher(self, obj):
        teacher = obj.teacher_assignment.teacher
        return {
            "id": str(teacher.id),
            "full_name": teacher.get_full_name() or teacher.username,
        }


class MobileHomeworkMetaSerializer(serializers.Serializer):
    requester_role = serializers.JSONField(allow_null=True)


class MobileHomeworkResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=True)
    code = serializers.CharField(default="MOBILE_CHILD_HOMEWORK_RETRIEVED")
    message = serializers.CharField()
    data = MobileHomeworkSerializer(many=True)
    meta = MobileHomeworkMetaSerializer()


class MobileHomeworkErrorSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=False)
    code = serializers.CharField()
    message = serializers.CharField()
    errors = serializers.JSONField(required=False)
    meta = MobileHomeworkMetaSerializer()
