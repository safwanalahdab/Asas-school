from rest_framework import serializers

from academics.models import (
    AcademicYear,
    GradeLevel,
    Section,
)

from .models import (
    Enrollment,
    Student,
)


class MobileAcademicYearSerializer(serializers.ModelSerializer):
    """
    تمثيل مختصر للسنة الدراسية الحالية للطالب.
    """

    name = serializers.CharField(
        read_only=True,
    )

    class Meta:
        model = AcademicYear

        fields = (
            "id",
            "name",
        )

        read_only_fields = fields


class MobileGradeLevelSerializer(serializers.ModelSerializer):
    """
    تمثيل مختصر للصف الدراسي الحالي.
    """

    class Meta:
        model = GradeLevel

        fields = (
            "id",
            "name",
        )

        read_only_fields = fields


class MobileSectionSerializer(serializers.ModelSerializer):
    """
    تمثيل مختصر للشعبة الحالية.
    """

    class Meta:
        model = Section

        fields = (
            "id",
            "name",
        )

        read_only_fields = fields


class MobileCurrentEnrollmentSerializer(serializers.ModelSerializer):
    """
    يمثل تسجيل الطالب في السنة الدراسية الفعالة فقط.
    """

    academic_year = MobileAcademicYearSerializer(
        read_only=True,
    )

    grade_level = MobileGradeLevelSerializer(
        source="section.grade_level",
        read_only=True,
    )

    section = MobileSectionSerializer(
        read_only=True,
    )

    usual_arrival_method_display = serializers.CharField(
        source="get_usual_arrival_method_display",
        read_only=True,
    )

    usual_departure_method_display = serializers.CharField(
        source="get_usual_departure_method_display",
        read_only=True,
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


class MobileChildSerializer(serializers.ModelSerializer):
    """
    بيانات الطالب المسموح بإرسالها إلى تطبيق ولي الأمر.
    """

    full_name = serializers.CharField(
        read_only=True,
    )

    gender_display = serializers.CharField(
        source="get_gender_display",
        read_only=True,
    )

    current_enrollment = serializers.SerializerMethodField()

    class Meta:
        model = Student

        fields = (
            "id",
            "first_name",
            "last_name",
            "full_name",
            "father_name",
            "mother_name",
            "birth_date",
            "gender",
            "gender_display",
            "current_enrollment",
        )

        read_only_fields = fields

    def get_current_enrollment(self, obj):
        """
        الـSelector يضع تسجيل السنة الفعالة داخل
        mobile_current_enrollments باستخدام Prefetch.

        القائمة ستكون:
        - فارغة إذا لم يوجد تسجيل حالي.
        - أو تحتوي تسجيلًا واحدًا فقط.
        """

        enrollments = getattr(
            obj,
            "mobile_current_enrollments",
            [],
        )

        if not enrollments:
            return None

        return MobileCurrentEnrollmentSerializer(
            enrollments[0],
        ).data


class MobileChildrenResponseMetaSerializer(serializers.Serializer):
    """
    يمثل meta الذي يضيفه ArabicApiResponseMixin.
    """

    requester_role = serializers.JSONField(
        allow_null=True,
    )


class MobileChildrenSuccessEnvelopeSerializer(serializers.Serializer):
    """
    الهيكل العام لأي Response ناجح
    في Mobile Children APIs.
    """

    success = serializers.BooleanField(
        default=True,
    )

    code = serializers.CharField()

    message = serializers.CharField()

    meta = MobileChildrenResponseMetaSerializer()


class MobileChildrenListResponseSerializer(
    MobileChildrenSuccessEnvelopeSerializer
):
    """
    Swagger schema لاستجابة قائمة الأبناء.
    """

    code = serializers.CharField(
        default="MOBILE_CHILDREN_RETRIEVED",
    )

    data = MobileChildSerializer(
        many=True,
    )


class MobileChildDetailResponseSerializer(
    MobileChildrenSuccessEnvelopeSerializer
):
    """
    Swagger schema لاستجابة تفاصيل ابن واحد.
    """

    code = serializers.CharField(
        default="MOBILE_CHILD_RETRIEVED",
    )

    data = MobileChildSerializer()


class MobileChildrenErrorResponseSerializer(serializers.Serializer):
    """
    الشكل الموحد لأخطاء:
    401
    403
    404

    في Mobile Children APIs.
    """

    success = serializers.BooleanField(
        default=False,
    )

    code = serializers.CharField()

    message = serializers.CharField()

    meta = MobileChildrenResponseMetaSerializer()