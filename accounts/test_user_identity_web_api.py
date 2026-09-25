from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User


class UserIdentityWebApiTests(TestCase):
    users_url = "/api/v1/accounts/users/"

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="identity-api-admin",
            password="StrongPass!493",
            role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
        )
        self.admin.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="accounts",
            codename__in=("add_user", "change_user", "view_user"),
        ))
        self.client.force_authenticate(self.admin, token={"client": "web"})

    def create_user(self, *, username, role, national_id=None, phone_number=""):
        payload = {
            "username": username,
            "role": role,
            "phone_number": phone_number,
        }
        if national_id is not None:
            payload["national_id"] = national_id
        return self.client.post(self.users_url, payload, format="json")

    def test_create_teacher_persists_national_id_and_phone_number(self):
        response = self.create_user(
            username="identity-api-teacher",
            role=User.Role.TEACHER,
            national_id="012345678901",
            phone_number="0933123456",
        )
        self.assertEqual(response.status_code, 201)
        teacher = User.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(teacher.national_id, "012345678901")
        self.assertEqual(teacher.phone_number, "0933123456")

    def test_create_guardian_persists_national_id_and_phone_number(self):
        response = self.create_user(
            username="identity-api-guardian",
            role=User.Role.GUARDIAN,
            national_id="998877665544",
            phone_number="0999111222",
        )
        self.assertEqual(response.status_code, 201)
        guardian = User.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(guardian.national_id, "998877665544")
        self.assertEqual(guardian.phone_number, "0999111222")

    def test_patch_updates_national_id_and_phone_number(self):
        user = User.objects.create_user(
            username="identity-api-update",
            role=User.Role.TEACHER,
            national_id="111111111111",
            phone_number="0900000000",
        )
        response = self.client.patch(
            f"{self.users_url}{user.pk}/",
            {
                "national_id": "222222222222",
                "phone_number": "0911111111",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.national_id, "222222222222")
        self.assertEqual(user.phone_number, "0911111111")

    def test_create_and_retrieve_responses_include_identity_fields(self):
        response = self.create_user(
            username="identity-api-response",
            role=User.Role.TEACHER,
            national_id="333333333333",
            phone_number="0922222222",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["data"]["national_id"], "333333333333")
        self.assertEqual(response.data["data"]["phone_number"], "0922222222")

        detail = self.client.get(
            f"{self.users_url}{response.data['data']['id']}/"
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["data"]["national_id"], "333333333333")
        self.assertEqual(detail.data["data"]["phone_number"], "0922222222")

    def test_duplicate_national_id_is_rejected(self):
        first = self.create_user(
            username="identity-api-duplicate-one",
            role=User.Role.TEACHER,
            national_id="444444444444",
        )
        self.assertEqual(first.status_code, 201)
        second = self.create_user(
            username="identity-api-duplicate-two",
            role=User.Role.GUARDIAN,
            national_id="444444444444",
        )
        self.assertEqual(second.status_code, 400)
        self.assertIn("national_id", second.data["errors"])

    def test_blank_identity_values_follow_model_policy(self):
        first = self.create_user(
            username="identity-api-blank-one",
            role=User.Role.TEACHER,
            national_id="",
            phone_number="",
        )
        second = self.create_user(
            username="identity-api-blank-two",
            role=User.Role.GUARDIAN,
            national_id="",
            phone_number="",
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        users = User.objects.filter(
            username__in=("identity-api-blank-one", "identity-api-blank-two")
        )
        self.assertEqual(users.filter(national_id__isnull=True).count(), 2)
        self.assertEqual(users.filter(phone_number="").count(), 2)

    def test_existing_business_permission_and_account_scope_are_unchanged(self):
        teacher_actor = User.objects.create_user(
            username="identity-api-unprivileged-actor",
            password="StrongPass!493",
            role=User.Role.TEACHER,
            must_change_password=False,
        )
        self.client.force_authenticate(teacher_actor, token={"client": "web"})
        create_response = self.client.post(
            self.users_url,
            {
                "username": "identity-api-forbidden-create",
                "role": User.Role.TEACHER,
                "national_id": "555555555555",
                "phone_number": "0944444444",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 403)
        self.assertFalse(
            User.objects.filter(username="identity-api-forbidden-create").exists()
        )
