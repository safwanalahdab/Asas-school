from datetime import date
from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase
from rest_framework.exceptions import ValidationError

from accounts.models import User
from students.models import GuardianStudent, Student, StudentHealthProfile
from students.services import ensure_student_health_profile, register_student


class RegisterStudentServiceTests(TestCase):
    student_data = {
        "first_name": "سارة",
        "last_name": "علي",
        "birth_date": date(2018, 2, 1),
        "gender": Student.Gender.FEMALE,
    }
    guardian_data = {
        "national_id": "01234567890",
        "first_name": "أحمد",
        "last_name": "علي",
        "phone_number": "0999999999",
        "relationship": "أب",
    }

    def test_registration_without_guardian_creates_student_and_profile(self):
        with patch(
            "students.services.ensure_student_health_profile",
            wraps=ensure_student_health_profile,
        ) as ensure_profile:
            result = register_student(student_data=self.student_data)

        student = result["student"]
        self.assertTrue(Student.objects.filter(pk=student.pk).exists())
        self.assertTrue(StudentHealthProfile.objects.filter(student=student).exists())
        self.assertFalse(GuardianStudent.objects.exists())
        self.assertEqual(
            result["guardian_account"],
            {
                "status": "not_created",
                "username": None,
                "temporary_password": None,
            },
        )
        ensure_profile.assert_called_once_with(student)

    def test_supplied_health_data_is_stored(self):
        result = register_student(
            student_data=self.student_data,
            health_profile_data={
                "blood_type": "A+",
                "allergies": "Peanuts",
            },
        )

        profile = result["student"].health_profile
        self.assertEqual(profile.blood_type, "A+")
        self.assertEqual(profile.allergies, "Peanuts")
        self.assertEqual(profile.health_notes, "")

    def test_new_guardian_is_created_with_temporary_password(self):
        result = register_student(
            student_data=self.student_data,
            guardian_data=self.guardian_data,
        )

        account = result["guardian_account"]
        guardian = User.objects.get(username=self.guardian_data["national_id"])
        link = GuardianStudent.objects.get(student=result["student"])
        self.assertEqual(account["status"], "created")
        self.assertEqual(account["username"], guardian.username)
        self.assertIsNotNone(account["temporary_password"])
        self.assertEqual(guardian.role, User.Role.GUARDIAN)
        self.assertEqual(guardian.national_id, self.guardian_data["national_id"])
        self.assertEqual(guardian.phone_number, self.guardian_data["phone_number"])
        self.assertEqual(link.guardian, guardian)
        self.assertEqual(link.relationship, self.guardian_data["relationship"])
        self.assertTrue(guardian.check_password(account["temporary_password"]))
        self.assertTrue(guardian.must_change_password)
        self.assertIsNotNone(guardian.temporary_password_expires_at)
        self.assertNotEqual(guardian.password, account["temporary_password"])
        self.assertNotIn(account["temporary_password"], guardian.password)

    def test_existing_guardian_is_reused_without_modification(self):
        guardian = User.objects.create_user(
            username="existing-guardian-login",
            national_id=self.guardian_data["national_id"],
            phone_number="0988888888",
            password="ExistingStrong!934",
            role=User.Role.GUARDIAN,
            first_name="Existing",
            last_name="Guardian",
            must_change_password=False,
        )
        original_password = guardian.password
        original_token_version = guardian.token_version
        original_expiry = guardian.temporary_password_expires_at

        result = register_student(
            student_data=self.student_data,
            guardian_data=self.guardian_data,
        )

        guardian.refresh_from_db()
        self.assertEqual(User.objects.filter(username=guardian.username).count(), 1)
        self.assertEqual(GuardianStudent.objects.get(student=result["student"]).guardian, guardian)
        self.assertEqual(result["guardian_account"]["status"], "linked_existing")
        self.assertIsNone(result["guardian_account"]["temporary_password"])
        self.assertEqual(guardian.password, original_password)
        self.assertEqual(guardian.token_version, original_token_version)
        self.assertEqual(guardian.must_change_password, False)
        self.assertEqual(guardian.temporary_password_expires_at, original_expiry)
        self.assertEqual(guardian.first_name, "Existing")
        self.assertEqual(guardian.last_name, "Guardian")
        self.assertEqual(guardian.phone_number, "0988888888")
        self.assertEqual(
            result["guardian_account"]["username"], "existing-guardian-login"
        )

    def test_non_guardian_national_id_rolls_back_registration(self):
        existing_user = User.objects.create_user(
            username="teacher-with-national-id",
            national_id=self.guardian_data["national_id"],
            password="ExistingStrong!934",
            role=User.Role.TEACHER,
            first_name="Existing",
            last_name="Teacher",
            must_change_password=False,
        )
        original_password = existing_user.password
        original_token_version = existing_user.token_version

        with self.assertRaises(ValidationError) as error:
            register_student(
                student_data=self.student_data,
                guardian_data=self.guardian_data,
            )

        self.assertIn("guardian", error.exception.detail)
        self.assertEqual(Student.objects.count(), 0)
        self.assertEqual(StudentHealthProfile.objects.count(), 0)
        self.assertEqual(GuardianStudent.objects.count(), 0)
        existing_user.refresh_from_db()
        self.assertEqual(existing_user.role, User.Role.TEACHER)
        self.assertEqual(existing_user.password, original_password)
        self.assertEqual(existing_user.token_version, original_token_version)

    def test_occupied_username_without_matching_national_id_rolls_back(self):
        existing_user = User.objects.create_user(
            username=self.guardian_data["national_id"],
            password="ExistingStrong!934",
            role=User.Role.TEACHER,
            must_change_password=False,
        )

        with self.assertRaises(ValidationError) as error:
            register_student(
                student_data=self.student_data,
                guardian_data=self.guardian_data,
            )

        self.assertIn("national_id", error.exception.detail["guardian"])
        self.assertEqual(Student.objects.count(), 0)
        self.assertEqual(StudentHealthProfile.objects.count(), 0)
        self.assertEqual(GuardianStudent.objects.count(), 0)
        self.assertEqual(User.objects.count(), 1)
        existing_user.refresh_from_db()
        self.assertIsNone(existing_user.national_id)

    def test_guardian_uniqueness_race_returns_validation_error_and_rolls_back(self):
        with patch.object(User, "save", side_effect=IntegrityError), self.assertRaises(
            ValidationError
        ) as error:
            register_student(
                student_data=self.student_data,
                guardian_data=self.guardian_data,
            )

        self.assertIn("national_id", error.exception.detail["guardian"])
        self.assertEqual(Student.objects.count(), 0)
        self.assertEqual(StudentHealthProfile.objects.count(), 0)
        self.assertEqual(GuardianStudent.objects.count(), 0)

    def test_guardian_link_failure_rolls_back_every_new_record(self):
        with patch(
            "students.services.GuardianStudent.objects.create",
            side_effect=RuntimeError("link creation failed"),
        ), self.assertRaises(RuntimeError):
            register_student(
                student_data=self.student_data,
                guardian_data=self.guardian_data,
            )

        self.assertEqual(Student.objects.count(), 0)
        self.assertEqual(StudentHealthProfile.objects.count(), 0)
        self.assertEqual(GuardianStudent.objects.count(), 0)
        self.assertFalse(
            User.objects.filter(username=self.guardian_data["national_id"]).exists()
        )
