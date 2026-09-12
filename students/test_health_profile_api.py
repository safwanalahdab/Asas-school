from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import resolve
from rest_framework.test import APIClient

from students.models import Student, StudentHealthProfile
from students.views import StudentHealthProfileView


User = get_user_model()


class StudentHealthProfileApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.student = Student.objects.create(
            first_name="سارة",
            last_name="علي",
            birth_date="2018-02-01",
            gender=Student.Gender.FEMALE,
        )
        self.profile = StudentHealthProfile.objects.create(
            student=self.student,
            blood_type="O+",
            chronic_diseases="الربو",
            allergies="الغبار",
            permanent_medications="دواء دائم",
            special_health_needs="متابعة",
            emergency_contact_name="أحمد علي",
            emergency_contact_phone="0999999999",
            health_notes="ملاحظة",
        )
        self.url = f"/api/v1/students/{self.student.pk}/health-profile/"

    def authenticate(self, role):
        user = User.objects.create_user(
            username=f"health-{role}-{User.objects.count()}",
            password="Strong!934",
            role=role,
            must_change_password=False,
        )
        self.client.force_authenticate(user, token={"client": "web"})
        return user

    def assert_can_get_and_patch(self, user):
        self.client.force_authenticate(user, token={"client": "web"})
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], "HEALTH_PROFILE_RETRIEVED")
        response = self.client.patch(
            self.url, {"allergies": "البنسلين"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], "HEALTH_PROFILE_UPDATED")

    def test_school_admin_can_get(self):
        self.authenticate(User.Role.SCHOOL_ADMIN)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_secretariat_can_get_and_patch(self):
        self.assert_can_get_and_patch(self.authenticate(User.Role.SECRETARIAT))

    def test_supervisor_can_get_and_patch(self):
        self.assert_can_get_and_patch(self.authenticate(User.Role.SUPERVISOR))

    def test_superuser_can_get_and_patch(self):
        self.assert_can_get_and_patch(
            User.objects.create_superuser(
                username="health-root", password="RootStrong!934"
            )
        )

    def test_disallowed_roles_receive_403(self):
        for role in (
            User.Role.TEACHER,
            User.Role.GUARDIAN,
            User.Role.TECH_SUPPORT,
        ):
            with self.subTest(role=role):
                self.authenticate(role)
                self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_unauthenticated_request_receives_401(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_get_returns_only_the_requested_students_profile(self):
        other = Student.objects.create(
            first_name="ليلى",
            last_name="حسن",
            birth_date="2017-03-02",
            gender=Student.Gender.FEMALE,
        )
        StudentHealthProfile.objects.create(student=other, blood_type="A-")
        self.authenticate(User.Role.SCHOOL_ADMIN)

        data = self.client.get(self.url).data["data"]

        self.assertEqual(str(data["student"]), str(self.student.pk))
        self.assertEqual(data["blood_type"], "O+")
        self.assertNotIn("first_name", data)

    def test_patch_one_field_preserves_omitted_fields_and_student(self):
        self.authenticate(User.Role.SECRETARIAT)
        student_values = (self.student.first_name, self.student.last_name)

        response = self.client.patch(
            self.url, {"allergies": "البنسلين"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.student.refresh_from_db()
        self.assertEqual(self.profile.allergies, "البنسلين")
        self.assertEqual(self.profile.blood_type, "O+")
        self.assertEqual(self.profile.permanent_medications, "دواء دائم")
        self.assertEqual(self.profile.emergency_contact_name, "أحمد علي")
        self.assertEqual(self.profile.emergency_contact_phone, "0999999999")
        self.assertEqual(self.profile.health_notes, "ملاحظة")
        self.assertEqual(
            (self.student.first_name, self.student.last_name), student_values
        )

    def test_patch_multiple_fields(self):
        self.authenticate(User.Role.SUPERVISOR)
        response = self.client.patch(
            self.url,
            {"blood_type": "AB+", "health_notes": "تحديث"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.blood_type, "AB+")
        self.assertEqual(self.profile.health_notes, "تحديث")

    def test_unsupported_methods_receive_405(self):
        self.authenticate(User.Role.SCHOOL_ADMIN)
        for method in (self.client.post, self.client.put, self.client.delete):
            with self.subTest(method=method.__name__):
                self.assertEqual(method(self.url, {}, format="json").status_code, 405)

    def test_unknown_student_receives_404(self):
        self.authenticate(User.Role.SCHOOL_ADMIN)
        missing_url = "/api/v1/students/00000000-0000-0000-0000-000000000000/health-profile/"
        self.assertEqual(self.client.get(missing_url).status_code, 404)

    def test_missing_profile_is_safely_restored(self):
        self.profile.delete()
        self.authenticate(User.Role.SCHOOL_ADMIN)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            StudentHealthProfile.objects.filter(student=self.student).exists()
        )

    def test_url_resolves_to_standalone_view(self):
        self.assertIs(resolve(self.url).func.view_class, StudentHealthProfileView)
