from rest_framework import serializers

from academics.models import AcademicYear
from attendance.models import AttendanceRecord
from behavior.models import BehaviorNote
from finance.models import Payment, StudentDiscount, StudentFinancialAccount
from grades.models import AssessmentSection, StudentScore

from .models import Enrollment, GuardianStudent, Student, StudentHealthProfile


class ProfileStudentSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    gender_display = serializers.CharField(source="get_gender_display", read_only=True)

    class Meta:
        model = Student
        fields = (
            "id",
            "full_name",
            "first_name",
            "father_name",
            "mother_name",
            "last_name",
            "first_name_en",
            "last_name_en",
            "gender",
            "gender_display",
            "birth_date",
            "is_active",
        )
        read_only_fields = fields


class ProfileGuardianSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="guardian_id", read_only=True)
    username = serializers.CharField(source="guardian.username", read_only=True)
    full_name = serializers.SerializerMethodField()
    phone_number = serializers.CharField(source="guardian.phone_number", read_only=True)
    email = serializers.EmailField(source="guardian.email", read_only=True)
    is_active = serializers.BooleanField(source="guardian.is_active", read_only=True)

    class Meta:
        model = GuardianStudent
        fields = (
            "id",
            "username",
            "full_name",
            "relationship",
            "phone_number",
            "email",
            "is_active",
        )
        read_only_fields = fields

    def get_full_name(self, obj):
        full_name = obj.guardian.get_full_name().strip()
        return full_name or obj.guardian.username


class ProfileHealthSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentHealthProfile
        fields = (
            "id",
            "blood_type",
            "chronic_diseases",
            "allergies",
            "permanent_medications",
            "special_health_needs",
            "emergency_contact_name",
            "emergency_contact_phone",
            "health_notes",
        )
        read_only_fields = fields


class ProfileAcademicYearSerializer(serializers.ModelSerializer):
    name = serializers.CharField(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = AcademicYear
        fields = ("id", "name", "status", "status_display")
        read_only_fields = fields


class ProfileGradeLevelSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)


class ProfileSectionSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)


class ProfileEnrollmentSerializer(serializers.ModelSerializer):
    academic_year = ProfileAcademicYearSerializer(read_only=True)
    grade_level = ProfileGradeLevelSerializer(source="section.grade_level", read_only=True)
    section = ProfileSectionSerializer(read_only=True)
    usual_arrival_method_display = serializers.CharField(
        source="get_usual_arrival_method_display", read_only=True
    )
    usual_departure_method_display = serializers.CharField(
        source="get_usual_departure_method_display", read_only=True
    )

    class Meta:
        model = Enrollment
        fields = (
            "id",
            "enrollment_date",
            "academic_year",
            "grade_level",
            "section",
            "usual_arrival_method",
            "usual_arrival_method_display",
            "usual_departure_method",
            "usual_departure_method_display",
        )
        read_only_fields = fields


class ProfileAttendanceRecordSerializer(serializers.ModelSerializer):
    attendance_date = serializers.DateField(source="sheet.attendance_date", read_only=True)
    section = ProfileSectionSerializer(source="sheet.section", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    arrival_method_display = serializers.CharField(
        source="get_arrival_method_display", read_only=True
    )
    departure_method_display = serializers.CharField(
        source="get_departure_method_display", read_only=True
    )
    absence_type_display = serializers.CharField(
        source="get_absence_type_display", read_only=True
    )
    absence_reason_source_display = serializers.CharField(
        source="get_absence_reason_source_display", read_only=True
    )

    class Meta:
        model = AttendanceRecord
        fields = (
            "id",
            "attendance_date",
            "section",
            "status",
            "status_display",
            "arrival_time",
            "arrival_method",
            "arrival_method_display",
            "departure_time",
            "departure_method",
            "departure_method_display",
            "absence_type",
            "absence_type_display",
            "absence_reason",
            "absence_reason_source",
            "absence_reason_source_display",
        )
        read_only_fields = fields


class ProfileTermSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    number = serializers.IntegerField(read_only=True)
    number_display = serializers.CharField(source="get_number_display", read_only=True)


class ProfileSubjectSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)


class ProfileGradeSerializer(serializers.ModelSerializer):
    assessment_title = serializers.CharField(source="assessment.title", read_only=True)
    assessment_date = serializers.DateField(source="assessment.assessment_date", read_only=True)
    term = ProfileTermSerializer(source="assessment.term", read_only=True)
    subject = ProfileSubjectSerializer(
        source="assessment.grade_subject.subject", read_only=True
    )
    recorded_section = ProfileSectionSerializer(read_only=True)
    max_score = serializers.DecimalField(
        source="assessment.max_score", max_digits=7, decimal_places=2, read_only=True
    )
    publication_status = serializers.ChoiceField(
        choices=AssessmentSection.Status.choices, read_only=True, allow_null=True
    )
    published_at = serializers.DateTimeField(
        source="publication_published_at", read_only=True, allow_null=True
    )

    class Meta:
        model = StudentScore
        fields = (
            "id",
            "assessment",
            "assessment_title",
            "assessment_date",
            "term",
            "subject",
            "recorded_section",
            "score",
            "max_score",
            "publication_status",
            "published_at",
        )
        read_only_fields = fields


class ProfileBehaviorNoteSerializer(serializers.ModelSerializer):
    note_type_display = serializers.CharField(source="get_note_type_display", read_only=True)

    class Meta:
        model = BehaviorNote
        fields = (
            "id",
            "note_type",
            "note_type_display",
            "title",
            "description",
            "occurred_on",
            "created_at",
        )
        read_only_fields = fields


class ProfileFinancialAccountSerializer(serializers.ModelSerializer):
    base_tuition_usd = serializers.DecimalField(
        source="tuition_plan.base_tuition_usd",
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = StudentFinancialAccount
        fields = ("id", "tuition_plan", "base_tuition_usd")
        read_only_fields = fields


class ProfilePaymentSerializer(serializers.ModelSerializer):
    currency_display = serializers.CharField(source="get_currency_display", read_only=True)

    class Meta:
        model = Payment
        fields = (
            "id",
            "currency",
            "currency_display",
            "amount",
            "exchange_rate_syp_per_usd",
            "equivalent_usd",
            "paid_at",
            "is_cancelled",
            "cancellation_reason",
            "cancelled_at",
            "created_at",
        )
        read_only_fields = fields


class ProfileDiscountSerializer(serializers.ModelSerializer):
    discount_type_display = serializers.CharField(
        source="get_discount_type_display", read_only=True
    )
    currency_display = serializers.CharField(source="get_currency_display", read_only=True)

    class Meta:
        model = StudentDiscount
        fields = (
            "id",
            "discount_type",
            "discount_type_display",
            "value",
            "currency",
            "currency_display",
            "exchange_rate_syp_per_usd",
            "equivalent_usd",
            "reason",
            "is_cancelled",
            "cancellation_reason",
            "cancelled_at",
            "created_at",
        )
        read_only_fields = fields


class ProfilePageSerializer(serializers.Serializer):
    count = serializers.IntegerField(read_only=True)
    page = serializers.IntegerField(read_only=True)
    page_size = serializers.IntegerField(read_only=True)
    total_pages = serializers.IntegerField(read_only=True)
    next = serializers.IntegerField(read_only=True, allow_null=True)
    previous = serializers.IntegerField(read_only=True, allow_null=True)
    results = serializers.ListField(read_only=True)


class AttendanceSummarySerializer(serializers.Serializer):
    total_recorded_days = serializers.IntegerField(read_only=True)
    present_count = serializers.IntegerField(read_only=True)
    absent_count = serializers.IntegerField(read_only=True)
    excused_absence_count = serializers.IntegerField(read_only=True)
    unexcused_absence_count = serializers.IntegerField(read_only=True)
    attendance_rate_percentage = serializers.DecimalField(
        max_digits=5, decimal_places=2, read_only=True
    )


class BehaviorSummarySerializer(serializers.Serializer):
    total_notes_count = serializers.IntegerField(read_only=True)
    positive_notes_count = serializers.IntegerField(read_only=True)
    negative_notes_count = serializers.IntegerField(read_only=True)


class PointsSummarySerializer(serializers.Serializer):
    total_points = serializers.IntegerField(read_only=True)
    entries_count = serializers.IntegerField(read_only=True)


class FinanceSummarySerializer(serializers.Serializer):
    base_tuition_usd = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    total_discounts_usd = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    net_tuition_usd = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    total_paid_usd = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    remaining_usd = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)


class ProfileAttendanceSerializer(serializers.Serializer):
    summary = AttendanceSummarySerializer(read_only=True)
    records = ProfilePageSerializer(read_only=True)


class ProfileBehaviorSerializer(serializers.Serializer):
    summary = BehaviorSummarySerializer(read_only=True)
    notes = ProfilePageSerializer(read_only=True)


class ProfilePointsSerializer(serializers.Serializer):
    summary = PointsSummarySerializer(read_only=True)


class ProfileFinanceSerializer(serializers.Serializer):
    account = ProfileFinancialAccountSerializer(read_only=True, allow_null=True)
    summary = FinanceSummarySerializer(read_only=True, allow_null=True)
    payments = ProfilePageSerializer(read_only=True)
    discounts = ProfilePageSerializer(read_only=True)


class StudentProfileSerializer(serializers.Serializer):
    student = ProfileStudentSerializer(read_only=True)
    guardians = ProfileGuardianSerializer(many=True, read_only=True)
    health_profile = ProfileHealthSerializer(read_only=True, allow_null=True)
    academic_year = ProfileAcademicYearSerializer(read_only=True, allow_null=True)
    enrollment = ProfileEnrollmentSerializer(read_only=True, allow_null=True)
    attendance = ProfileAttendanceSerializer(read_only=True)
    grades = ProfilePageSerializer(read_only=True)
    behavior = ProfileBehaviorSerializer(read_only=True)
    points = ProfilePointsSerializer(read_only=True)
    finance = ProfileFinanceSerializer(read_only=True)


class StudentProfileMetaSerializer(serializers.Serializer):
    requester_role = serializers.DictField(read_only=True, allow_null=True)


class StudentProfileResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(read_only=True)
    code = serializers.CharField(read_only=True)
    message = serializers.CharField(read_only=True)
    data = StudentProfileSerializer(read_only=True)
    meta = StudentProfileMetaSerializer(read_only=True)


class StudentProfileErrorSerializer(serializers.Serializer):
    success = serializers.BooleanField(read_only=True)
    code = serializers.CharField(read_only=True)
    message = serializers.CharField(read_only=True)
    errors = serializers.DictField(read_only=True, required=False)
    meta = StudentProfileMetaSerializer(read_only=True)
