from rest_framework import serializers

from academics.models import Section
from students.models import Enrollment
from .domain import ATTENDANCE_FIELDS, normalize_and_validate_record
from .models import AttendanceRecord, AttendanceSheet


class AttendanceRecordInputSerializer(serializers.Serializer):
    enrollment = serializers.PrimaryKeyRelatedField(queryset=Enrollment.objects.all())
    status = serializers.ChoiceField(choices=AttendanceRecord.Status.choices)
    arrival_time = serializers.TimeField(required=False, allow_null=True)
    arrival_method = serializers.ChoiceField(choices=Enrollment.TransportationMethod.choices, required=False, allow_blank=True)
    departure_time = serializers.TimeField(required=False, allow_null=True)
    departure_method = serializers.ChoiceField(choices=Enrollment.TransportationMethod.choices, required=False, allow_blank=True)
    absence_type = serializers.ChoiceField(choices=AttendanceRecord.AbsenceType.choices, required=False, allow_blank=True)
    absence_reason = serializers.CharField(required=False, allow_blank=True)
    absence_reason_source = serializers.ChoiceField(choices=AttendanceRecord.AbsenceReasonSource.choices, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        normalize_and_validate_record(attrs, final=True)
        return attrs


class AttendanceRecordSerializer(serializers.ModelSerializer):
    student_display = serializers.CharField(source="enrollment.student.full_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    arrival_method_display = serializers.CharField(source="get_arrival_method_display", read_only=True)
    departure_method_display = serializers.CharField(source="get_departure_method_display", read_only=True)
    absence_type_display = serializers.CharField(source="get_absence_type_display", read_only=True)
    absence_reason_source_display = serializers.CharField(source="get_absence_reason_source_display", read_only=True)

    class Meta:
        model = AttendanceRecord
        fields = ("id", "sheet", "enrollment", "student_display", *ATTENDANCE_FIELDS,
                  "status_display", "arrival_method_display", "departure_method_display",
                  "absence_type_display", "absence_reason_source_display", "created_at", "updated_at")
        read_only_fields = ("id", "sheet", "enrollment", "created_at", "updated_at")

    def validate(self, attrs):
        normalize_and_validate_record(attrs, current=self.instance)
        return attrs


class AttendanceSheetSerializer(serializers.ModelSerializer):
    section_display = serializers.CharField(source="section.__str__", read_only=True)
    grade_level_display = serializers.CharField(source="section.grade_level.name", read_only=True)
    created_by_display = serializers.CharField(source="created_by.__str__", read_only=True)
    records = AttendanceRecordSerializer(many=True, read_only=True)

    class Meta:
        model = AttendanceSheet
        fields = ("id", "section", "section_display", "grade_level_display", "attendance_date",
                  "created_by", "created_by_display", "records", "created_at", "updated_at")
        read_only_fields = fields


class AttendanceSheetCreateSerializer(serializers.Serializer):
    section = serializers.PrimaryKeyRelatedField(queryset=Section.objects.all())
    records = AttendanceRecordInputSerializer(many=True, allow_empty=False)


class BulkRecordInputSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=AttendanceRecord.Status.choices, required=False)
    arrival_time = serializers.TimeField(required=False, allow_null=True)
    arrival_method = serializers.ChoiceField(choices=Enrollment.TransportationMethod.choices, required=False, allow_blank=True)
    departure_time = serializers.TimeField(required=False, allow_null=True)
    departure_method = serializers.ChoiceField(choices=Enrollment.TransportationMethod.choices, required=False, allow_blank=True)
    absence_type = serializers.ChoiceField(choices=AttendanceRecord.AbsenceType.choices, required=False, allow_blank=True)
    absence_reason = serializers.CharField(required=False, allow_blank=True)
    absence_reason_source = serializers.ChoiceField(choices=AttendanceRecord.AbsenceReasonSource.choices, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class BulkAttendanceUpdateSerializer(serializers.Serializer):
    records = BulkRecordInputSerializer(many=True, allow_empty=False)


class NormalDepartureSerializer(serializers.Serializer):
    departure_time = serializers.TimeField()
    departure_method = serializers.ChoiceField(choices=Enrollment.TransportationMethod.choices)
