from django.contrib.auth import get_user_model
from django.test import TestCase

from students.models import GuardianStudent, Student, StudentHealthProfile
from students.registration_serializers import StudentRegistrationSerializer


User = get_user_model()


class StudentRegistrationSerializerTests(TestCase):
    minimal_student = {
        "first_name": "سارة",
        "last_name": "علي",
        "birth_date": "2018-02-01",
        "gender": "female",
    }

    def serializer(self, **extra):
        return StudentRegistrationSerializer(
            data={"student": self.minimal_student, **extra}
        )

    def test_minimal_student_without_optional_objects_is_valid(self):
        serializer = self.serializer()

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn("health_profile", serializer.validated_data)
        self.assertNotIn("guardian", serializer.validated_data)

    def test_full_student_and_health_data_are_valid(self):
        student = {
            **self.minimal_student,
            "father_name": "أحمد",
            "mother_name": "ريم",
            "first_name_en": "Sara",
            "last_name_en": "Ali",
        }
        health_profile = {
            "blood_type": "A+",
            "chronic_diseases": "",
            "allergies": "Peanuts",
            "permanent_medications": "",
            "special_health_needs": "",
            "emergency_contact_name": "Ahmad Ali",
            "emergency_contact_phone": "0999999999",
            "health_notes": "Follow-up required",
        }
        serializer = StudentRegistrationSerializer(
            data={"student": student, "health_profile": health_profile}
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["health_profile"], health_profile)

    def test_valid_guardian_with_national_id(self):
        serializer = self.serializer(
            guardian={
                "national_id": "01234567890",
                "first_name": "أحمد",
                "last_name": "علي",
                "phone_number": " 0999999999 ",
                "relationship": "أب",
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["guardian"]["national_id"],
            "01234567890",
        )
        self.assertEqual(
            serializer.validated_data["guardian"]["phone_number"],
            "0999999999",
        )

    def test_guardian_phone_number_is_optional(self):
        serializer = self.serializer(guardian=self.guardian_data("123456"))

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn("phone_number", serializer.validated_data["guardian"])

    def test_guardian_phone_number_max_length_has_arabic_error(self):
        guardian = self.guardian_data("123456")
        guardian["phone_number"] = "1" * 31
        serializer = self.serializer(guardian=guardian)

        self.assertFalse(serializer.is_valid())
        error = serializer.errors["guardian"]["phone_number"][0]
        self.assertTrue(any("\u0600" <= character <= "\u06ff" for character in error))

    def test_arabic_indic_digits_are_normalized(self):
        serializer = self.serializer(
            guardian=self.guardian_data("٠١٢-٣٤٥ ٦٧٨٩٠")
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["guardian"]["national_id"],
            "01234567890",
        )

    def test_persian_digits_are_normalized(self):
        serializer = self.serializer(guardian=self.guardian_data("۰۱۲۳۴۵۶۷۸۹"))

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["guardian"]["national_id"],
            "0123456789",
        )

    def test_spaces_and_hyphens_are_removed(self):
        serializer = self.serializer(
            guardian=self.guardian_data(" 01 23-45 67890 ")
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["guardian"]["national_id"],
            "01234567890",
        )

    def test_non_digit_national_id_is_rejected(self):
        serializer = self.serializer(guardian=self.guardian_data("123A-456"))

        self.assertFalse(serializer.is_valid())
        self.assertIn("national_id", serializer.errors["guardian"])

    def test_national_id_requires_guardian_first_name(self):
        guardian = self.guardian_data("123456")
        guardian.pop("first_name")
        serializer = self.serializer(guardian=guardian)

        self.assertFalse(serializer.is_valid())
        self.assertIn("first_name", serializer.errors["guardian"])

    def test_national_id_requires_guardian_last_name(self):
        guardian = self.guardian_data("123456")
        guardian.pop("last_name")
        serializer = self.serializer(guardian=guardian)

        self.assertFalse(serializer.is_valid())
        self.assertIn("last_name", serializer.errors["guardian"])

    def test_national_id_requires_relationship(self):
        guardian = self.guardian_data("123456")
        guardian.pop("relationship")
        serializer = self.serializer(guardian=guardian)

        self.assertFalse(serializer.is_valid())
        self.assertIn("relationship", serializer.errors["guardian"])

    def test_guardian_fields_without_national_id_are_rejected(self):
        serializer = self.serializer(guardian={"first_name": "أحمد"})

        self.assertFalse(serializer.is_valid())
        self.assertIn("national_id", serializer.errors["guardian"])

    def test_empty_guardian_object_requires_national_id(self):
        serializer = self.serializer(guardian={})

        self.assertFalse(serializer.is_valid())
        self.assertIn("national_id", serializer.errors["guardian"])

    def test_invalid_gender_is_rejected(self):
        serializer = StudentRegistrationSerializer(
            data={"student": {**self.minimal_student, "gender": "invalid"}}
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("gender", serializer.errors["student"])

    def test_missing_required_student_fields_are_rejected(self):
        serializer = StudentRegistrationSerializer(data={"student": {}})

        self.assertFalse(serializer.is_valid())
        for field_name in ("first_name", "last_name", "birth_date", "gender"):
            self.assertIn(field_name, serializer.errors["student"])

    def test_validation_creates_no_database_records(self):
        serializer = self.serializer(
            health_profile={"blood_type": "O+"},
            guardian=self.guardian_data("123456789"),
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(Student.objects.count(), 0)
        self.assertEqual(StudentHealthProfile.objects.count(), 0)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(GuardianStudent.objects.count(), 0)

    @staticmethod
    def guardian_data(national_id):
        return {
            "national_id": national_id,
            "first_name": "أحمد",
            "last_name": "علي",
            "relationship": "أب",
        }
