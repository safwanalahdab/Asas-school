from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from students.models import Student, StudentHealthProfile
from students.services import ensure_student_health_profile


User = get_user_model()


class LegacyStudentHealthProfileCreationTests(TestCase):
    endpoint = "/api/v1/students/students/"
    payload = {
        "first_name": "Sara",
        "last_name": "Ali",
        "birth_date": "2018-02-01",
        "gender": "female",
    }

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="student-health-admin",
            password="Strong!934",
            role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
        )
        self.client.force_authenticate(self.admin, token={"client": "web"})

    def test_legacy_post_creates_one_profile_without_exposing_health_fields(self):
        response = self.client.post(self.endpoint, self.payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["code"], "STUDENT_CREATED")
        student = Student.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(
            StudentHealthProfile.objects.filter(student=student).count(),
            1,
        )
        health_fields = {
            "health_profile",
            "blood_type",
            "chronic_diseases",
            "allergies",
            "permanent_medications",
            "special_health_needs",
            "emergency_contact_name",
            "emergency_contact_phone",
            "health_notes",
        }
        self.assertTrue(health_fields.isdisjoint(response.data["data"]))

    def test_ensure_health_profile_is_idempotent(self):
        student = Student.objects.create(
            first_name="Omar",
            last_name="Hasan",
            birth_date=date(2017, 3, 2),
            gender=Student.Gender.MALE,
        )

        first_profile = ensure_student_health_profile(student)
        first_profile.health_notes = "Existing notes"
        first_profile.save(update_fields=["health_notes"])
        second_profile = ensure_student_health_profile(student)

        self.assertEqual(first_profile.pk, second_profile.pk)
        self.assertEqual(second_profile.health_notes, "Existing notes")
        self.assertEqual(
            StudentHealthProfile.objects.filter(student=student).count(),
            1,
        )

    def test_profile_failure_rolls_back_student_creation(self):
        initial_count = Student.objects.count()

        with patch(
            "students.views.ensure_student_health_profile",
            side_effect=RuntimeError("profile creation failed"),
        ):
            response = self.client.post(self.endpoint, self.payload, format="json")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(Student.objects.count(), initial_count)

    def test_guardian_remains_unauthorized_to_create_student(self):
        guardian = User.objects.create_user(
            username="student-health-guardian",
            password="Strong!934",
            role=User.Role.GUARDIAN,
            must_change_password=False,
        )
        self.client.force_authenticate(guardian, token={"client": "web"})

        response = self.client.post(self.endpoint, self.payload, format="json")

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.data["success"])
        self.assertEqual(Student.objects.count(), 0)
