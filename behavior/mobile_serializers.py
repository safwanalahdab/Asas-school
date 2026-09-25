from rest_framework import serializers

from .models import BehaviorNote, StudentPointEntry


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


class MobileBehaviorRequesterRoleSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()


class MobileBehaviorPaginationSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total_pages = serializers.IntegerField()


class MobileBehaviorMetaSerializer(serializers.Serializer):
    requester_role = MobileBehaviorRequesterRoleSerializer(allow_null=True)
    pagination = MobileBehaviorPaginationSerializer(required=False)


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


class MobilePointsQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)

    def validate(self, attrs):
        if (
            attrs.get("date_from")
            and attrs.get("date_to")
            and attrs["date_from"] > attrs["date_to"]
        ):
            raise serializers.ValidationError({
                "date_to": "يجب أن يكون تاريخ النهاية مساويًا لتاريخ البداية أو بعده."
            })
        return attrs


class MobilePointEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentPointEntry
        fields = (
            "id",
            "points",
            "note",
            "occurred_on",
        )
        read_only_fields = fields


class MobilePointsSummarySerializer(serializers.Serializer):
    total_points = serializers.IntegerField()
    entries_count = serializers.IntegerField()


class MobilePointsDataSerializer(serializers.Serializer):
    summary = MobilePointsSummarySerializer()
    entries = MobilePointEntrySerializer(many=True)


class MobilePointsPaginationSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total_pages = serializers.IntegerField()


class MobilePointsMetaSerializer(serializers.Serializer):
    requester_role = MobileBehaviorRequesterRoleSerializer(allow_null=True)
    pagination = MobilePointsPaginationSerializer(required=False)


class MobilePointsResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=True)
    code = serializers.CharField(default="MOBILE_CHILD_POINTS_RETRIEVED")
    message = serializers.CharField()
    data = MobilePointsDataSerializer()
    meta = MobilePointsMetaSerializer()


class MobilePointsErrorSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=False)
    code = serializers.CharField()
    message = serializers.CharField()
    errors = serializers.JSONField(required=False)
    meta = MobilePointsMetaSerializer()
