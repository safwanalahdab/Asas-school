from rest_framework import serializers

from .models import AttendanceRecord


class MobileAttendanceQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    status = serializers.ChoiceField(
        choices=(AttendanceRecord.Status.PRESENT, AttendanceRecord.Status.ABSENT),
        required=False,
    )

    def validate(self, attrs):
        if attrs.get("date_from") and attrs.get("date_to") and attrs["date_from"] > attrs["date_to"]:
            raise serializers.ValidationError({
                "date_to": "يجب أن يكون تاريخ النهاية مساويًا لتاريخ البداية أو بعده."
            })
        return attrs


class MobileAttendanceStudentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    full_name = serializers.CharField()


class MobileAttendanceAcademicYearSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class MobileAttendanceRecordSerializer(serializers.ModelSerializer):
    attendance_date = serializers.DateField(source="sheet.attendance_date")
    status_display = serializers.CharField(source="get_status_display")
    arrival_method_display = serializers.CharField(source="get_arrival_method_display")
    departure_method_display = serializers.CharField(source="get_departure_method_display")
    absence_type_display = serializers.CharField(source="get_absence_type_display")
    absence_reason_source_display = serializers.CharField(source="get_absence_reason_source_display")

    class Meta:
        model = AttendanceRecord
        fields = (
            "id", "attendance_date", "status", "status_display",
            "arrival_time", "arrival_method", "arrival_method_display",
            "departure_time", "departure_method", "departure_method_display",
            "absence_type", "absence_type_display", "absence_reason",
            "absence_reason_source", "absence_reason_source_display",
        )
        read_only_fields = fields


class MobileTodayAttendanceDataSerializer(serializers.Serializer):
    student = MobileAttendanceStudentSerializer()
    academic_year = MobileAttendanceAcademicYearSerializer(allow_null=True)
    date = serializers.DateField()
    is_recorded = serializers.BooleanField()
    status = serializers.CharField(allow_null=True)
    status_display = serializers.CharField()
    record = MobileAttendanceRecordSerializer(allow_null=True)


class MobileAttendanceSummarySerializer(serializers.Serializer):
    total_recorded_days = serializers.IntegerField()
    present_count = serializers.IntegerField()
    absent_count = serializers.IntegerField()
    excused_absence_count = serializers.IntegerField()
    unexcused_absence_count = serializers.IntegerField()
    attendance_rate_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)


class MobileAttendancePaginationSerializer(serializers.Serializer):
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total_pages = serializers.IntegerField()
    total_items = serializers.IntegerField()


class MobileAttendanceHistoryDataSerializer(serializers.Serializer):
    student = MobileAttendanceStudentSerializer()
    academic_year = MobileAttendanceAcademicYearSerializer(allow_null=True)
    summary = MobileAttendanceSummarySerializer()
    records = MobileAttendanceRecordSerializer(many=True)
    pagination = MobileAttendancePaginationSerializer()


class MobileAttendanceMetaSerializer(serializers.Serializer):
    requester_role = serializers.JSONField(allow_null=True)


class MobileTodayAttendanceResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=True)
    code = serializers.CharField(default="MOBILE_CHILD_ATTENDANCE_RETRIEVED")
    message = serializers.CharField()
    data = MobileTodayAttendanceDataSerializer()
    meta = MobileAttendanceMetaSerializer()


class MobileAttendanceHistoryResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=True)
    code = serializers.CharField(default="MOBILE_CHILD_ATTENDANCE_HISTORY_RETRIEVED")
    message = serializers.CharField()
    data = MobileAttendanceHistoryDataSerializer()
    meta = MobileAttendanceMetaSerializer()


class MobileAttendanceErrorSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=False)
    code = serializers.CharField()
    message = serializers.CharField()
    errors = serializers.JSONField(required=False)
    meta = MobileAttendanceMetaSerializer()
