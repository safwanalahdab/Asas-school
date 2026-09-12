from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from students.models import GuardianStudent, Student, StudentHealthProfile


User = get_user_model()


class StudentHealthProfileFoundationTests(TestCase):
    def setUp(self):
        self.student = Student.objects.create(
            first_name="Ahmad",
            last_name="Khaled",
            birth_date=date(2018, 1, 1),
            gender=Student.Gender.MALE,
        )

    def test_student_english_names_are_optional(self):
        self.assertEqual(self.student.first_name_en, "")
        self.assertEqual(self.student.last_name_en, "")

    def test_guardian_relationship_is_optional(self):
        guardian = User.objects.create_user(
            username="health-profile-guardian",
            password="Strong!934",
            role=User.Role.GUARDIAN,
            must_change_password=False,
        )

        link = GuardianStudent.objects.create(
            guardian=guardian,
            student=self.student,
        )

        self.assertEqual(link.relationship, "")

    def test_health_profile_can_be_created_with_only_a_student(self):
        profile = StudentHealthProfile.objects.create(student=self.student)

        self.assertEqual(profile.blood_type, "")
        self.assertEqual(profile.chronic_diseases, "")
        self.assertEqual(profile.allergies, "")
        self.assertEqual(profile.permanent_medications, "")
        self.assertEqual(profile.special_health_needs, "")
        self.assertEqual(profile.emergency_contact_name, "")
        self.assertEqual(profile.emergency_contact_phone, "")
        self.assertEqual(profile.health_notes, "")
        self.assertEqual(self.student.health_profile, profile)

    def test_health_profile_is_one_to_one_with_student(self):
        StudentHealthProfile.objects.create(student=self.student)

        with self.assertRaises(IntegrityError), transaction.atomic():
            StudentHealthProfile.objects.create(student=self.student)
