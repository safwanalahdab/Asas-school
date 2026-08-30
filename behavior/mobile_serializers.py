from rest_framework import serializers

from .models import BehaviorNote


class MobileBehaviorStudentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    full_name = serializers.CharField()


class MobileBehaviorAcademicYearSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class MobileBehaviorSummarySerializer(serializers.Serializer):
    total_notes_count = serializers.IntegerField()
    positive_notes_count = serializers.IntegerField()
    negative_notes_count = serializers.IntegerField()


class MobileBehaviorNoteSerializer(serializers.ModelSerializer):
    note_type_display = serializers.CharField(source="get_note_type_display")

    class Meta:
        model = BehaviorNote
        fields = (
            "id",
            "note_type",
            "note_type_display",
            "title",
            "description",
            "occurred_on",
        )
        read_only_fields = fields


class MobileBehaviorDataSerializer(serializers.Serializer):
    student = MobileBehaviorStudentSerializer()
    academic_year = MobileBehaviorAcademicYearSerializer(allow_null=True)
    summary = MobileBehaviorSummarySerializer()
    notes = MobileBehaviorNoteSerializer(many=True)


class MobileBehaviorMetaSerializer(serializers.Serializer):
    requester_role = serializers.JSONField(allow_null=True)


class MobileBehaviorResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=True)
    code = serializers.CharField(default="MOBILE_CHILD_BEHAVIOR_RETRIEVED")
    message = serializers.CharField()
    data = MobileBehaviorDataSerializer()
    meta = MobileBehaviorMetaSerializer()


class MobileBehaviorErrorSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=False)
    code = serializers.CharField()
    message = serializers.CharField()
    errors = serializers.JSONField(required=False)
    meta = MobileBehaviorMetaSerializer()
