from copy import deepcopy

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import resolve
from rest_framework.test import APIClient

from students.models import GuardianStudent, Student, StudentHealthProfile
from students.views import StudentRegistrationView, StudentViewSet


User = get_user_model()


class StudentRegistrationApiTests(TestCase):
    endpoint = "/api/v1/students/register/"
    legacy_endpoint = "/api/v1/students/students/"
    minimal_payload = {
        "student": {
            "first_name": "سارة",
            "last_name": "علي",
            "birth_date": "2018-02-01",
            "gender": "female",
        }
    }

    def setUp(self):
        self.client = APIClient()

    def authenticate(self, role):
        user = User.objects.create_user(
            username=f"registration-{role}-{User.objects.count()}",
            password="Strong!934",
            role=role,
            must_change_password=False,
        )
        self.client.force_authenticate(user, token={"client": "web"})
        return user

    def test_management_roles_can_register_students(self):
        for role in (
            User.Role.SCHOOL_ADMIN,
            User.Role.SECRETARIAT,
            User.Role.SUPERVISOR,
        ):
            with self.subTest(role=role):
                self.authenticate(role)
                response = self.client.post(
                    self.endpoint, self.minimal_payload, format="json"
                )
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.data["code"], "STUDENT_REGISTERED")

    def test_superuser_can_register_student(self):
        user = User.objects.create_superuser(
            username="registration-superuser",
            password="Strong!934",
        )
        self.client.force_authenticate(user, token={"client": "web"})

        response = self.client.post(self.endpoint, self.minimal_payload, format="json")

        self.assertEqual(response.status_code, 201)

    def test_unauthorized_roles_receive_403(self):
        for role in (
            User.Role.TEACHER,
            User.Role.GUARDIAN,
            User.Role.TECH_SUPPORT,
        ):
            with self.subTest(role=role):
                self.authenticate(role)
                response = self.client.post(
                    self.endpoint, self.minimal_payload, format="json"
                )
                self.assertEqual(response.status_code, 403)
        self.assertEqual(Student.objects.count(), 0)

    def test_unauthenticated_request_receives_401(self):
        response = self.client.post(self.endpoint, self.minimal_payload, format="json")

        self.assertEqual(response.status_code, 401)

    def test_minimal_registration_creates_profile_and_no_guardian(self):
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.post(self.endpoint, self.minimal_payload, format="json")

        self.assertEqual(response.status_code, 201)
        student_id = response.data["data"]["student"]["id"]
        self.assertTrue(Student.objects.filter(pk=student_id).exists())
        self.assertTrue(StudentHealthProfile.objects.filter(student_id=student_id).exists())
        self.assertFalse(GuardianStudent.objects.exists())
        self.assertEqual(
            response.data["data"]["guardian_account"],
            {
                "status": "not_created",
                "username": None,
                "temporary_password": None,
            },
        )

    def test_health_profile_values_are_persisted(self):
        self.authenticate(User.Role.SECRETARIAT)
        payload = {
            **deepcopy(self.minimal_payload),
            "health_profile": {"blood_type": "O+", "health_notes": "متابعة"},
        }

        response = self.client.post(self.endpoint, payload, format="json")

        self.assertEqual(response.status_code, 201)
        profile = StudentHealthProfile.objects.get(
            student_id=response.data["data"]["student"]["id"]
        )
        self.assertEqual(profile.blood_type, "O+")
        self.assertEqual(profile.health_notes, "متابعة")

    def test_english_student_names_are_returned_by_registration(self):
        self.authenticate(User.Role.SCHOOL_ADMIN)
        payload = deepcopy(self.minimal_payload)
        payload["student"].update(
            {"first_name_en": "Sara", "last_name_en": "Ali"}
        )

        response = self.client.post(self.endpoint, payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["data"]["student"]["first_name_en"], "Sara")
        self.assertEqual(response.data["data"]["student"]["last_name_en"], "Ali")

    def test_new_guardian_returns_working_temporary_password(self):
        self.authenticate(User.Role.SUPERVISOR)

        response = self.client.post(
            self.endpoint, self.payload_with_guardian("01234567890"), format="json"
        )

        self.assertEqual(response.status_code, 201)
        account = response.data["data"]["guardian_account"]
        guardian = User.objects.get(username="01234567890")
        self.assertEqual(account["status"], "created")
        self.assertEqual(account["username"], guardian.username)
        self.assertEqual(
            set(account),
            {"status", "username", "temporary_password"},
        )
        self.assertEqual(guardian.national_id, "01234567890")
        self.assertEqual(guardian.phone_number, "0999999999")
        self.assertTrue(guardian.check_password(account["temporary_password"]))
        self.assertTrue(
            GuardianStudent.objects.filter(
                student_id=response.data["data"]["student"]["id"],
                guardian=guardian,
            ).exists()
        )
        self.assertNotIn("password", response.data["data"]["student"])
        self.assertNotIn("temporary_password", response.data["data"]["student"])

    def test_existing_guardian_is_linked_without_password_change(self):
        self.authenticate(User.Role.SCHOOL_ADMIN)
        guardian = User.objects.create_user(
            username="existing-guardian-login",
            national_id="123456789",
            phone_number="0988888888",
            password="ExistingStrong!934",
            role=User.Role.GUARDIAN,
            first_name="Existing",
            last_name="Guardian",
            must_change_password=False,
        )
        original_password = guardian.password

        response = self.client.post(
            self.endpoint,
            self.payload_with_guardian(guardian.national_id),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        account = response.data["data"]["guardian_account"]
        self.assertEqual(account["status"], "linked_existing")
        self.assertEqual(account["username"], guardian.username)
        self.assertIsNone(account["temporary_password"])
        guardian.refresh_from_db()
        self.assertEqual(guardian.password, original_password)
        self.assertEqual(guardian.first_name, "Existing")
        self.assertEqual(guardian.last_name, "Guardian")
        self.assertEqual(guardian.phone_number, "0988888888")

    def test_non_guardian_national_id_returns_400_and_rolls_back(self):
        self.authenticate(User.Role.SCHOOL_ADMIN)
        User.objects.create_user(
            username="teacher-national-id",
            national_id="987654321",
            password="ExistingStrong!934",
            role=User.Role.TEACHER,
            must_change_password=False,
        )

        response = self.client.post(
            self.endpoint,
            self.payload_with_guardian("987654321"),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("national_id", response.data["errors"]["guardian"])
        self.assertEqual(Student.objects.count(), 0)
        self.assertEqual(StudentHealthProfile.objects.count(), 0)

    def test_occupied_username_returns_controlled_400_and_rolls_back(self):
        self.authenticate(User.Role.SCHOOL_ADMIN)
        User.objects.create_user(
            username="987654321",
            password="ExistingStrong!934",
            role=User.Role.TEACHER,
            must_change_password=False,
        )

        response = self.client.post(
            self.endpoint,
            self.payload_with_guardian("987654321"),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("national_id", response.data["errors"]["guardian"])
        self.assertEqual(Student.objects.count(), 0)
        self.assertEqual(StudentHealthProfile.objects.count(), 0)
        self.assertEqual(GuardianStudent.objects.count(), 0)

    def test_arabic_digits_are_normalized_for_guardian_username(self):
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.post(
            self.endpoint,
            self.payload_with_guardian("٠١٢-٣٤٥ ٦٧٨٩٠"),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        guardian = User.objects.get(username="01234567890")
        self.assertEqual(guardian.national_id, "01234567890")
        self.assertEqual(
            response.data["data"]["guardian_account"]["username"],
            "01234567890",
        )

    def test_invalid_request_returns_arabic_errors_without_records(self):
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.post(self.endpoint, {"student": {}}, format="json")

        self.assertEqual(response.status_code, 400)
        errors = response.data["errors"]["student"]
        self.assertIn("first_name", errors)
        self.assertTrue(
            any("\u0600" <= char <= "\u06ff" for char in errors["first_name"][0])
        )
        self.assertEqual(Student.objects.count(), 0)
        self.assertEqual(StudentHealthProfile.objects.count(), 0)
        self.assertEqual(GuardianStudent.objects.count(), 0)

    def test_endpoint_resolution_and_legacy_post_contract(self):
        self.assertIs(resolve(self.endpoint).func.view_class, StudentRegistrationView)
        self.assertIs(
            resolve("/api/v1/students/students/register/").func.cls,
            StudentViewSet,
        )
        self.authenticate(User.Role.SCHOOL_ADMIN)
        legacy_payload = self.minimal_payload["student"]

        response = self.client.post(self.legacy_endpoint, legacy_payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["code"], "STUDENT_CREATED")
        self.assertNotIn("temporary_password", response.data["data"])
        student_id = response.data["data"]["id"]
        get_response = self.client.get(f"{self.legacy_endpoint}{student_id}/")
        self.assertEqual(get_response.status_code, 200)
        self.assertNotIn("temporary_password", get_response.data["data"])

    @classmethod
    def payload_with_guardian(cls, national_id):
        return {
            **deepcopy(cls.minimal_payload),
            "guardian": {
                "national_id": national_id,
                "first_name": "أحمد",
                "last_name": "علي",
                "phone_number": "0999999999",
                "relationship": "أب",
            },
        }
