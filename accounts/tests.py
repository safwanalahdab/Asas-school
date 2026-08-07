from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.policies import can_create_role
from accounts.serializers import WebLoginSerializer, WebTokenRefreshSerializer
from accounts.services import assign_temporary_password, generate_temporary_password


User = get_user_model()


class PasswordLifecycleTests(TestCase):
    def test_temporary_password_is_eight_digits_hashed_and_expires(self):
        user = User(username="new-user", role=User.Role.GUARDIAN)
        password = assign_temporary_password(user)
        self.assertRegex(password, r"^\d{8}$")
        self.assertNotEqual(user.password, password)
        self.assertTrue(user.check_password(password))
        self.assertTrue(user.must_change_password)
        self.assertGreater(
            user.temporary_password_expires_at,
            timezone.now() + timedelta(hours=71),
        )

    def test_generator_preserves_eight_digit_width(self):
        self.assertEqual(len(generate_temporary_password()), 8)

    def test_superuser_is_exempt_from_temporary_password_cycle(self):
        user = User.objects.create_superuser(
            username="root", password="StrongRoot!934"
        )
        self.assertFalse(user.must_change_password)
        self.assertIsNone(user.temporary_password_expires_at)

    def test_expired_temporary_password_rejects_login_and_refresh(self):
        user = User.objects.create_user(
            username="expired",
            password="Temporary!934",
            role=User.Role.TEACHER,
            must_change_password=True,
            temporary_password_expires_at=timezone.now() - timedelta(seconds=1),
        )
        with self.assertRaises(AuthenticationFailed):
            WebLoginSerializer(
                data={"identifier": user.username, "password": "Temporary!934"}
            ).is_valid(raise_exception=True)
        refresh = RefreshToken.for_user(user)
        refresh["client"] = "web"
        refresh["token_version"] = user.token_version
        with self.assertRaises(AuthenticationFailed):
            WebTokenRefreshSerializer(data={"refresh": str(refresh)}).is_valid(
                raise_exception=True
            )


class AccountPolicyTests(TestCase):
    def actor(self, role, superuser=False):
        return User(
            username=role or "root",
            role=role,
            is_active=True,
            is_superuser=superuser,
        )

    def test_creation_matrix(self):
        secretariat = self.actor(User.Role.SECRETARIAT)
        supervisor = self.actor(User.Role.SUPERVISOR)
        admin = self.actor(User.Role.SCHOOL_ADMIN)
        self.assertTrue(can_create_role(secretariat, User.Role.GUARDIAN))
        self.assertTrue(can_create_role(secretariat, User.Role.SUPERVISOR))
        self.assertFalse(can_create_role(secretariat, User.Role.TEACHER))
        self.assertTrue(can_create_role(supervisor, User.Role.GUARDIAN))
        self.assertFalse(can_create_role(supervisor, User.Role.SUPERVISOR))
        self.assertTrue(
            all(can_create_role(admin, role) for role, _ in User.Role.choices)
        )


class AccountManagementApiTests(TestCase):
    password = "Initial!934"

    def setUp(self):
        self.client = APIClient()
        self.admin = self.make_user("admin", User.Role.SCHOOL_ADMIN)
        self.secretariat = self.make_user("secretariat", User.Role.SECRETARIAT)
        self.supervisor = self.make_user("supervisor", User.Role.SUPERVISOR)
        self.teacher = self.make_user("teacher", User.Role.TEACHER)
        self.guardian = self.make_user("guardian", User.Role.GUARDIAN)
        self.tech_support = self.make_user("support", User.Role.TECH_SUPPORT)
        self.root = User.objects.create_superuser(
            username="root-api", password="RootStrong!934"
        )

    def make_user(self, username, role, **kwargs):
        return User.objects.create_user(
            username=username,
            password=self.password,
            role=role,
            must_change_password=False,
            **kwargs,
        )

    def authenticate(self, user):
        self.client.force_authenticate(user, token={"client": "web"})

    def test_role_visibility_and_direct_uuid_non_disclosure(self):
        self.authenticate(self.admin)
        admin_names = {
            item["username"]
            for item in self.client.get("/api/v1/accounts/users/").data["results"]
        }
        self.assertIn(self.secretariat.username, admin_names)
        self.assertNotIn(self.root.username, admin_names)

        self.authenticate(self.secretariat)
        response = self.client.get("/api/v1/accounts/users/")
        names = {item["username"] for item in response.data["results"]}
        self.assertNotIn(self.admin.username, names)
        self.assertNotIn(self.root.username, names)
        self.assertEqual(
            self.client.get(f"/api/v1/accounts/users/{self.admin.pk}/").status_code,
            404,
        )

        self.authenticate(self.supervisor)
        roles = {
            item["role"]
            for item in self.client.get("/api/v1/accounts/users/").data["results"]
        }
        self.assertEqual(roles, {User.Role.GUARDIAN})

    def test_teacher_guardian_and_tech_support_cannot_use_management(self):
        for user in (self.teacher, self.guardian, self.tech_support):
            with self.subTest(role=user.role):
                self.authenticate(user)
                self.assertEqual(
                    self.client.get("/api/v1/accounts/users/").status_code, 403
                )

    def test_list_supports_pagination_search_filtering_and_ordering(self):
        self.authenticate(self.admin)
        response = self.client.get(
            "/api/v1/accounts/users/",
            {
                "search": "guardian",
                "role": User.Role.GUARDIAN,
                "is_active": "true",
                "must_change_password": "false",
                "ordering": "username",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], "USERS_RETRIEVED")
        self.assertIn("count", response.data)
        self.assertEqual(
            [item["username"] for item in response.data["results"]], ["guardian"]
        )

    def test_create_user_returns_one_time_hashed_temporary_password(self):
        self.authenticate(self.admin)
        response = self.client.post(
            "/api/v1/accounts/users/",
            {"username": "guardian2", "role": User.Role.GUARDIAN},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["code"], "USER_CREATED")
        password = response.data["temporary_password"]
        user = User.objects.get(username="guardian2")
        self.assertTrue(user.check_password(password))
        self.assertTrue(user.must_change_password)
        self.assertIsNotNone(user.temporary_password_expires_at)
        self.assertNotIn(password, user.password)

    def test_create_rejects_forbidden_field_and_unauthorized_role(self):
        self.authenticate(self.secretariat)
        forbidden = self.client.post(
            "/api/v1/accounts/users/",
            {
                "username": "bad-security",
                "role": User.Role.GUARDIAN,
                "password": "injected",
            },
            format="json",
        )
        self.assertEqual(forbidden.status_code, 400)
        denied = self.client.post(
            "/api/v1/accounts/users/",
            {"username": "bad-role", "role": User.Role.SCHOOL_ADMIN},
            format="json",
        )
        self.assertEqual(denied.status_code, 400)

    def test_retrieve_and_patch_safe_fields(self):
        self.authenticate(self.admin)
        detail_url = f"/api/v1/accounts/users/{self.teacher.pk}/"
        self.assertEqual(self.client.get(detail_url).status_code, 200)
        response = self.client.patch(
            detail_url, {"first_name": "Ahmad", "role": User.Role.GUARDIAN}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.first_name, "Ahmad")
        self.assertEqual(self.teacher.role, User.Role.GUARDIAN)

    def test_patch_rejects_security_fields_and_role_escalation(self):
        self.authenticate(self.admin)
        response = self.client.patch(
            f"/api/v1/accounts/users/{self.teacher.pk}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.authenticate(self.secretariat)
        response = self.client.patch(
            f"/api/v1/accounts/users/{self.guardian.pk}/",
            {"role": User.Role.TEACHER},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_put_and_delete_are_not_supported(self):
        self.authenticate(self.admin)
        url = f"/api/v1/accounts/users/{self.teacher.pk}/"
        self.assertEqual(self.client.put(url, {}, format="json").status_code, 405)
        self.assertEqual(self.client.delete(url).status_code, 405)

    def test_set_active_rules_and_token_version(self):
        self.authenticate(self.admin)
        url = f"/api/v1/accounts/users/{self.teacher.pk}/set-active/"
        old_version = self.teacher.token_version
        response = self.client.post(url, {"is_active": False}, format="json")
        self.assertEqual(response.status_code, 200)
        self.teacher.refresh_from_db()
        self.assertFalse(self.teacher.is_active)
        self.assertEqual(self.teacher.token_version, old_version + 1)

        unchanged = self.client.post(url, {"is_active": False}, format="json")
        self.assertEqual(unchanged.data["code"], "USER_ACTIVE_STATUS_UNCHANGED")
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.token_version, old_version + 1)

        self.client.post(url, {"is_active": True}, format="json")
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.is_active)
        self.assertEqual(self.teacher.token_version, old_version + 1)

    def test_set_active_denies_self_superuser_scope_secretariat_and_supervisor(self):
        self.authenticate(self.admin)
        self.assertEqual(
            self.client.post(
                f"/api/v1/accounts/users/{self.admin.pk}/set-active/",
                {"is_active": False},
                format="json",
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/accounts/users/{self.root.pk}/set-active/",
                {"is_active": False},
                format="json",
            ).status_code,
            404,
        )
        self.authenticate(self.secretariat)
        self.assertEqual(
            self.client.post(
                f"/api/v1/accounts/users/{self.admin.pk}/set-active/",
                {"is_active": False},
                format="json",
            ).status_code,
            404,
        )
        self.authenticate(self.supervisor)
        self.assertEqual(
            self.client.post(
                f"/api/v1/accounts/users/{self.guardian.pk}/set-active/",
                {"is_active": False},
                format="json",
            ).status_code,
            403,
        )

    def test_reset_password_updates_cycle_and_invalidates_tokens(self):
        old_refresh = RefreshToken.for_user(self.teacher)
        old_refresh["client"] = "web"
        old_refresh["token_version"] = self.teacher.token_version
        self.authenticate(self.admin)
        response = self.client.post(
            f"/api/v1/accounts/users/{self.teacher.pk}/reset-password/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], "PASSWORD_RESET")
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.check_password(response.data["temporary_password"]))
        self.assertTrue(self.teacher.must_change_password)
        self.assertIsNotNone(self.teacher.temporary_password_expires_at)
        self.assertEqual(self.teacher.token_version, 2)
        with self.assertRaises(AuthenticationFailed):
            WebTokenRefreshSerializer(data={"refresh": str(old_refresh)}).is_valid(
                raise_exception=True
            )

    def test_reset_password_permissions(self):
        self.authenticate(self.admin)
        self.assertEqual(
            self.client.post(
                f"/api/v1/accounts/users/{self.root.pk}/reset-password/"
            ).status_code,
            404,
        )
        self.authenticate(self.supervisor)
        self.assertEqual(
            self.client.post(
                f"/api/v1/accounts/users/{self.guardian.pk}/reset-password/"
            ).status_code,
            403,
        )

    def test_old_access_stays_invalid_after_reactivation(self):
        refresh = RefreshToken.for_user(self.teacher)
        refresh["client"] = "web"
        refresh["token_version"] = self.teacher.token_version
        old_access = str(refresh.access_token)
        self.authenticate(self.admin)
        url = f"/api/v1/accounts/users/{self.teacher.pk}/set-active/"
        self.client.post(url, {"is_active": False}, format="json")
        self.client.post(url, {"is_active": True}, format="json")
        self.client.force_authenticate(user=None)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {old_access}")
        self.assertEqual(self.client.get("/api/v1/auth/web/me/").status_code, 401)

    def test_change_password_rotates_to_current_version_cookies(self):
        refresh = RefreshToken.for_user(self.admin)
        refresh["client"] = "web"
        refresh["token_version"] = self.admin.token_version
        self.client.force_authenticate(user=None)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        response = self.client.post(
            "/api/v1/auth/web/change-password/",
            {
                "current_password": self.password,
                "new_password": "EntirelyNew!7284",
                "new_password_confirm": "EntirelyNew!7284",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.must_change_password)
        self.assertIsNone(self.admin.temporary_password_expires_at)
        self.assertEqual(self.admin.token_version, 2)
        self.assertIn(settings.JWT_ACCESS_COOKIE_NAME, response.cookies)
        self.assertIn(settings.JWT_REFRESH_COOKIE_NAME, response.cookies)
        new_access = response.cookies[settings.JWT_ACCESS_COOKIE_NAME].value
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {new_access}")
        self.assertEqual(self.client.get("/api/v1/auth/web/me/").status_code, 200)

    def test_change_password_validation_errors(self):
        self.authenticate(self.admin)
        url = "/api/v1/auth/web/change-password/"
        cases = [
            {
                "current_password": "wrong",
                "new_password": "EntirelyNew!7284",
                "new_password_confirm": "EntirelyNew!7284",
            },
            {
                "current_password": self.password,
                "new_password": "EntirelyNew!7284",
                "new_password_confirm": "Different!7284",
            },
            {
                "current_password": self.password,
                "new_password": "123",
                "new_password_confirm": "123",
            },
            {
                "current_password": self.password,
                "new_password": self.password,
                "new_password_confirm": self.password,
            },
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                response = self.client.post(url, payload, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data["code"], "VALIDATION_ERROR")


class WebMeUpdateTests(TestCase):
    url = "/api/v1/auth/web/me/"

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="profile-user",
            password="ProfileStrong!934",
            email="profile@example.com",
            role=User.Role.TEACHER,
            must_change_password=False,
        )
        self.other_user = User.objects.create_user(
            username="other-user",
            password="OtherStrong!934",
            email="other@example.com",
            role=User.Role.TEACHER,
            must_change_password=False,
        )

    def authenticate(self, client_name="web"):
        self.client.force_authenticate(
            self.user,
            token={"client": client_name},
        )

    def test_web_user_can_partially_update_first_name(self):
        self.authenticate()
        response = self.client.patch(
            self.url, {"first_name": "أحمد"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], "PROFILE_UPDATED")
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "أحمد")
        self.assertEqual(self.user.last_name, "")

    def test_web_user_can_update_last_name_and_valid_unique_email(self):
        self.authenticate()
        response = self.client.patch(
            self.url,
            {"last_name": "الخطيب", "email": "new-profile@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.last_name, "الخطيب")
        self.assertEqual(self.user.email, "new-profile@example.com")

    def test_current_email_is_allowed_case_insensitively(self):
        self.authenticate()
        response = self.client.patch(
            self.url, {"email": "PROFILE@example.com"}, format="json"
        )
        self.assertEqual(response.status_code, 200)

    def test_duplicate_email_is_rejected_case_insensitively(self):
        self.authenticate()
        response = self.client.patch(
            self.url, {"email": "OTHER@example.com"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "VALIDATION_ERROR")
        self.assertIn("email", response.data)

    def test_administrative_and_security_fields_cannot_be_modified(self):
        self.authenticate()
        original_password = self.user.password
        original_values = {
            "role": self.user.role,
            "is_active": self.user.is_active,
            "must_change_password": self.user.must_change_password,
            "token_version": self.user.token_version,
        }
        forbidden_values = {
            "role": User.Role.SCHOOL_ADMIN,
            "is_active": False,
            "must_change_password": True,
            "token_version": 999,
            "password": "InjectedPassword!934",
        }
        for field, value in forbidden_values.items():
            with self.subTest(field=field):
                response = self.client.patch(
                    self.url, {field: value}, format="json"
                )
                self.assertEqual(response.status_code, 400)

        self.user.refresh_from_db()
        for field, value in original_values.items():
            self.assertEqual(getattr(self.user, field), value)
        self.assertEqual(self.user.password, original_password)
        self.assertTrue(self.user.check_password("ProfileStrong!934"))

    def test_patch_always_targets_request_user_only(self):
        self.authenticate()
        response = self.client.patch(
            self.url,
            {"id": str(self.other_user.pk), "first_name": "محاولة"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.other_user.refresh_from_db()
        self.assertEqual(self.other_user.first_name, "")

    def test_unauthenticated_and_non_web_token_are_rejected(self):
        self.assertEqual(self.client.patch(self.url, {}, format="json").status_code, 401)
        self.authenticate(client_name="mobile")
        self.assertEqual(self.client.patch(self.url, {}, format="json").status_code, 403)

    def test_existing_get_me_behavior_still_works(self):
        self.authenticate()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], "CURRENT_USER_RETRIEVED")
        self.assertEqual(response.data["id"], str(self.user.pk))
        self.assertNotIn("password", response.data)
