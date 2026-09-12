from rest_framework import serializers

from .models import Student


REQUIRED_ERROR = "هذا الحقل مطلوب."
BLANK_ERROR = "لا يجوز أن يكون هذا الحقل فارغًا."


def normalize_national_id(value):
    digit_translation = str.maketrans(
        "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
        "01234567890123456789",
    )
    return value.strip().translate(digit_translation).replace(" ", "").replace("-", "")


class StudentInputSerializer(serializers.Serializer):
    first_name = serializers.CharField(
        max_length=100,
        error_messages={"required": REQUIRED_ERROR, "blank": BLANK_ERROR},
    )
    last_name = serializers.CharField(
        max_length=100,
        error_messages={"required": REQUIRED_ERROR, "blank": BLANK_ERROR},
    )
    father_name = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
    )
    mother_name = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
    )
    first_name_en = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
    )
    last_name_en = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
    )
    birth_date = serializers.DateField(
        error_messages={"required": REQUIRED_ERROR},
    )
    gender = serializers.ChoiceField(
        choices=Student.Gender.choices,
        error_messages={
            "required": REQUIRED_ERROR,
            "invalid_choice": "قيمة الجنس غير صالحة.",
        },
    )


class HealthProfileInputSerializer(serializers.Serializer):
    blood_type = serializers.CharField(max_length=10, required=False, allow_blank=True)
    chronic_diseases = serializers.CharField(required=False, allow_blank=True)
    allergies = serializers.CharField(required=False, allow_blank=True)
    permanent_medications = serializers.CharField(required=False, allow_blank=True)
    special_health_needs = serializers.CharField(required=False, allow_blank=True)
    emergency_contact_name = serializers.CharField(
        max_length=150,
        required=False,
        allow_blank=True,
    )
    emergency_contact_phone = serializers.CharField(
        max_length=30,
        required=False,
        allow_blank=True,
    )
    health_notes = serializers.CharField(required=False, allow_blank=True)


class GuardianInputSerializer(serializers.Serializer):
    national_id = serializers.CharField(required=False, allow_blank=True)
    first_name = serializers.CharField(
        max_length=150,
        required=False,
        allow_blank=True,
    )
    last_name = serializers.CharField(
        max_length=150,
        required=False,
        allow_blank=True,
    )
    phone_number = serializers.CharField(
        max_length=30,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        error_messages={
            "max_length": "يجب ألا يتجاوز رقم الهاتف 30 محرفًا.",
        },
    )
    relationship = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True,
    )

    def validate_national_id(self, value):
        normalized_value = normalize_national_id(value)
        if not normalized_value:
            raise serializers.ValidationError("الرقم الوطني مطلوب ولا يجوز أن يكون فارغًا.")
        if not normalized_value.isascii() or not normalized_value.isdigit():
            raise serializers.ValidationError("يجب أن يحتوي الرقم الوطني على أرقام فقط.")
        return normalized_value

    def validate(self, attrs):
        national_id = attrs.get("national_id")
        if not national_id:
            raise serializers.ValidationError(
                {"national_id": "الرقم الوطني مطلوب عند إدخال بيانات ولي الأمر."}
            )

        errors = {}
        for field_name, message in (
            ("first_name", "الاسم الأول لولي الأمر مطلوب."),
            ("last_name", "اسم عائلة ولي الأمر مطلوب."),
            ("relationship", "صلة القرابة مطلوبة."),
        ):
            if not attrs.get(field_name):
                errors[field_name] = message
        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class StudentRegistrationSerializer(serializers.Serializer):
    student = StudentInputSerializer(
        error_messages={"required": REQUIRED_ERROR},
    )
    health_profile = HealthProfileInputSerializer(required=False)
    guardian = GuardianInputSerializer(required=False)
