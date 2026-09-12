from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.mobile_serializers import MobileGuardianSerializer
from accounts.serializers import UserDetailSerializer, UserListSerializer


User = get_user_model()


class GuardianIdentityWebApiTests(TestCase):
    users_url = "/api/v1/accounts/users/"

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="identity-admin",
            password="Strong!934",
            role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
        )
        self.guardian = User.objects.create_user(
            username="guardian-login",
            password="Strong!934",
            email="guardian-search@example.com",
            first_name="خالد",
            last_name="تجربة",
            national_id="1234567899",
            phone_number="0933123456",
            role=User.Role.GUARDIAN,
            must_change_password=False,
        )
        self.teacher = User.objects.create_user(
            username="teacher-hidden",
            password="Strong!934",
            national_id="9988776655",
            phone_number="0911111111",
            role=User.Role.TEACHER,
            must_change_password=False,
        )

    def authenticate(self, user=None):
        self.client.force_authenticate(
            user or self.admin,
            token={"client": "web"},
        )

    def results_for(self, search):
        response = self.client.get(self.users_url, {"search": search})
        self.assertEqual(response.status_code, 200)
        return response.data["data"]["results"]

    def test_list_and_detail_include_read_only_identity_fields(self):
        self.authenticate()

        listed = self.results_for(self.guardian.username)[0]
        detail = self.client.get(f"{self.users_url}{self.guardian.pk}/")

        self.assertEqual(listed["national_id"], self.guardian.national_id)
        self.assertEqual(listed["phone_number"], self.guardian.phone_number)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["data"]["national_id"], self.guardian.national_id)
        self.assertEqual(
            detail.data["data"]["phone_number"], self.guardian.phone_number
        )
        self.assertIn("national_id", UserListSerializer.Meta.read_only_fields)
        self.assertIn("phone_number", UserDetailSerializer.Meta.read_only_fields)

    def test_search_by_national_id_and_phone_number(self):
        self.authenticate()

        for search in (self.guardian.national_id, self.guardian.phone_number):
            with self.subTest(search=search):
                self.assertEqual(
                    [item["id"] for item in self.results_for(search)],
                    [str(self.guardian.pk)],
                )

    def test_existing_search_fields_still_work(self):
        self.authenticate()

        for search in (
            self.guardian.username,
            self.guardian.email,
            self.guardian.first_name,
            self.guardian.last_name,
        ):
            with self.subTest(search=search):
                ids = {item["id"] for item in self.results_for(search)}
                self.assertIn(str(self.guardian.pk), ids)

    def test_identity_search_does_not_bypass_visibility_policy(self):
        supervisor = User.objects.create_user(
            username="identity-supervisor",
            password="Strong!934",
            role=User.Role.SUPERVISOR,
            must_change_password=False,
        )
        self.authenticate(supervisor)

        self.assertEqual(self.results_for(self.teacher.national_id), [])
        self.assertEqual(self.results_for(self.teacher.phone_number), [])

    def test_login_and_web_me_do_not_expose_identity_fields(self):
        self.admin.national_id = "1111222233"
        self.admin.phone_number = "0999000000"
        self.admin.save(update_fields=["national_id", "phone_number"])

        login = self.client.post(
            "/api/v1/auth/web/login/",
            {"identifier": self.admin.username, "password": "Strong!934"},
            format="json",
        )
        self.authenticate()
        me = self.client.get("/api/v1/auth/web/me/")

        self.assertEqual(login.status_code, 200)
        self.assertEqual(me.status_code, 200)
        for data in (login.data["data"]["user"], me.data["data"]):
            self.assertNotIn("national_id", data)
            self.assertNotIn("phone_number", data)

    def test_mobile_guardian_serializer_remains_unchanged(self):
        data = MobileGuardianSerializer(self.guardian).data

        self.assertNotIn("national_id", data)
        self.assertNotIn("phone_number", data)

    def test_user_serializers_do_not_nest_linked_students(self):
        fields = set(UserListSerializer.Meta.fields)

        self.assertFalse(
            fields.intersection(
                {"students", "guardian_student_links", "guardian_links"}
            )
        )
