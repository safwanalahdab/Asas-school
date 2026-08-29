from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts.mobile_permissions import IsMobileGuardian
from accounts.mobile_serializers import DUMMY_PASSWORD_HASH
from accounts.serializers import WebTokenRefreshSerializer
from accounts.throttles import MobileLoginRateThrottle, WebLoginRateThrottle

User = get_user_model()


class MobileAuthTests(TestCase):
    login_url = "/api/v1/auth/mobile/login/"
    refresh_url = "/api/v1/auth/mobile/refresh/"
    logout_url = "/api/v1/auth/mobile/logout/"
    me_url = "/api/v1/auth/mobile/me/"
    change_password_url = "/api/v1/auth/mobile/change-password/"

    def setUp(self):
        self.client = APIClient()
        self.password = "StrongPass!493"
        self.guardian = User.objects.create_user(
            username="guardian",
            email="guardian@example.com",
            password=self.password,
            role=User.Role.GUARDIAN,
            must_change_password=False,
        )

    def login(self, identifier="guardian", password=None):
        return self.client.post(
            self.login_url,
            {"identifier": identifier, "password": password or self.password},
            format="json",
            REMOTE_ADDR=f"198.51.100.{(sum(map(ord, self.id() + identifier)) % 250) + 1}",
        )

    def token_pair(self, user=None, client="mobile"):
        user = user or self.guardian
        refresh = RefreshToken.for_user(user)
        refresh["client"] = client
        refresh["token_version"] = user.token_version
        return str(refresh.access_token), str(refresh)

    def bearer(self, access):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    def test_guardian_login_by_username_and_email_returns_minimal_json_tokens(self):
        for identifier in (self.guardian.username, self.guardian.email.upper()):
            response = self.login(identifier)
            self.assertEqual(response.status_code, 200)
            data = response.data["data"]
            self.assertIn("access", data)
            self.assertIn("refresh", data)
            self.assertEqual(
                set(data["user"]),
                {"id", "username", "first_name", "last_name", "email", "role", "must_change_password"},
            )
            self.assertEqual(response.cookies, {})

    def test_login_claims_are_mobile_and_versioned(self):
        data = self.login().data["data"]
        access, refresh = AccessToken(data["access"]), RefreshToken(data["refresh"])
        for token in (access, refresh):
            self.assertEqual(token["client"], "mobile")
            self.assertEqual(token["token_version"], self.guardian.token_version)

    def test_login_bad_identifier_and_password_have_same_safe_error(self):
        unknown = self.login("does-not-exist", "wrong")
        wrong = self.login(password="wrong")
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(unknown.data["code"], wrong.data["code"])
        self.assertEqual(unknown.data["message"], wrong.data["message"])

    @patch("accounts.mobile_serializers.check_password")
    def test_unknown_identifier_performs_dummy_password_verification(self, mocked_check):
        response = self.login("does-not-exist", "wrong")
        self.assertEqual(response.status_code, 401)
        mocked_check.assert_called_once_with("wrong", DUMMY_PASSWORD_HASH)

    def test_login_rejects_every_non_guardian_role_and_inactive_guardian(self):
        for role in (
            User.Role.SCHOOL_ADMIN, User.Role.SECRETARIAT, User.Role.SUPERVISOR,
            User.Role.TEACHER, User.Role.TECH_SUPPORT,
        ):
            user = User.objects.create_user(
                username=f"user-{role}", password=self.password, role=role,
                must_change_password=False,
            )
            self.assertEqual(self.login(user.username).status_code, 401)
        self.guardian.is_active = False
        self.guardian.save(update_fields=["is_active"])
        self.assertEqual(self.login().status_code, 401)

    def test_temporary_password_policy_on_login(self):
        self.guardian.must_change_password = True
        self.guardian.temporary_password_expires_at = timezone.now() + timedelta(hours=1)
        self.guardian.save(update_fields=["must_change_password", "temporary_password_expires_at"])
        self.assertEqual(self.login().status_code, 200)
        self.guardian.temporary_password_expires_at = timezone.now() - timedelta(seconds=1)
        self.guardian.save(update_fields=["temporary_password_expires_at"])
        self.assertEqual(self.login().status_code, 401)

    def test_mobile_access_works_and_web_access_is_rejected(self):
        mobile_access, _ = self.token_pair()
        self.bearer(mobile_access)
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.data["data"]),
            {"id", "username", "first_name", "last_name", "email", "role", "must_change_password"},
        )
        web_access, _ = self.token_pair(client="web")
        self.bearer(web_access)
        self.assertEqual(self.client.get(self.me_url).status_code, 401)

    def test_mobile_access_is_rejected_by_web_me(self):
        access, _ = self.token_pair()
        self.bearer(access)
        self.assertEqual(self.client.get("/api/v1/auth/web/me/").status_code, 401)

    def test_access_checks_current_version_active_state_and_role(self):
        access, _ = self.token_pair()
        self.guardian.token_version += 1
        self.guardian.save(update_fields=["token_version"])
        self.bearer(access)
        self.assertEqual(self.client.get(self.me_url).status_code, 401)

        access, _ = self.token_pair()
        self.guardian.is_active = False
        self.guardian.save(update_fields=["is_active"])
        self.bearer(access)
        self.assertEqual(self.client.get(self.me_url).status_code, 401)

        self.guardian.is_active = True
        self.guardian.role = User.Role.TEACHER
        self.guardian.save(update_fields=["is_active", "role"])
        access, _ = self.token_pair()
        self.bearer(access)
        self.assertEqual(self.client.get(self.me_url).status_code, 403)

    def test_refresh_rotates_blacklists_and_preserves_claims(self):
        _, old_refresh = self.token_pair()
        response = self.client.post(self.refresh_url, {"refresh": old_refresh}, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.data["data"]
        for token in (AccessToken(data["access"]), RefreshToken(data["refresh"])):
            self.assertEqual(token["client"], "mobile")
            self.assertEqual(token["token_version"], self.guardian.token_version)
        self.assertEqual(
            self.client.post(self.refresh_url, {"refresh": old_refresh}, format="json").status_code,
            401,
        )

    def test_refresh_rejects_web_stale_inactive_changed_role_and_expired_temporary(self):
        _, web = self.token_pair(client="web")
        self.assertEqual(self.client.post(self.refresh_url, {"refresh": web}, format="json").status_code, 401)
        _, stale = self.token_pair()
        self.guardian.token_version += 1
        self.guardian.save(update_fields=["token_version"])
        self.assertEqual(self.client.post(self.refresh_url, {"refresh": stale}, format="json").status_code, 401)
        _, inactive = self.token_pair()
        self.guardian.is_active = False
        self.guardian.save(update_fields=["is_active"])
        self.assertEqual(self.client.post(self.refresh_url, {"refresh": inactive}, format="json").status_code, 401)
        self.guardian.is_active = True
        self.guardian.role = User.Role.TEACHER
        self.guardian.save(update_fields=["is_active", "role"])
        _, changed = self.token_pair()
        self.assertEqual(self.client.post(self.refresh_url, {"refresh": changed}, format="json").status_code, 401)
        self.guardian.role = User.Role.GUARDIAN
        self.guardian.must_change_password = True
        self.guardian.temporary_password_expires_at = timezone.now() - timedelta(seconds=1)
        self.guardian.save(update_fields=["role", "must_change_password", "temporary_password_expires_at"])
        _, expired = self.token_pair()
        self.assertEqual(self.client.post(self.refresh_url, {"refresh": expired}, format="json").status_code, 401)

    def test_web_refresh_serializer_rejects_mobile_refresh(self):
        _, mobile = self.token_pair()
        with self.assertRaises(AuthenticationFailed):
            WebTokenRefreshSerializer(data={"refresh": mobile}).is_valid(
                raise_exception=True
            )

    def test_valid_temporary_password_allows_me_and_refresh(self):
        self.guardian.must_change_password = True
        self.guardian.temporary_password_expires_at = timezone.now() + timedelta(hours=1)
        self.guardian.save(update_fields=["must_change_password", "temporary_password_expires_at"])
        access, refresh = self.token_pair()
        self.bearer(access)
        self.assertEqual(self.client.get(self.me_url).status_code, 200)
        self.client.credentials()
        self.assertEqual(self.client.post(self.refresh_url, {"refresh": refresh}, format="json").status_code, 200)

    def test_logout_blacklists_only_supplied_token_and_is_idempotent(self):
        original_version = self.guardian.token_version
        _, first = self.token_pair()
        _, second = self.token_pair()
        self.assertEqual(self.client.post(self.logout_url, {"refresh": first}, format="json").status_code, 200)
        self.assertEqual(self.client.post(self.logout_url, {"refresh": first}, format="json").status_code, 200)
        with self.assertRaises(TokenError):
            RefreshToken(first)
        self.assertEqual(self.client.post(self.refresh_url, {"refresh": second}, format="json").status_code, 200)
        self.guardian.refresh_from_db()
        self.assertEqual(self.guardian.token_version, original_version)

    def test_logout_rejects_web_and_access_tokens(self):
        access, _ = self.token_pair()
        _, web = self.token_pair(client="web")
        for token in (access, web, "forged"):
            self.assertEqual(self.client.post(self.logout_url, {"refresh": token}, format="json").status_code, 401)

    def test_change_password_reuses_shared_logic_and_revokes_old_tokens(self):
        self.guardian.must_change_password = True
        self.guardian.temporary_password_expires_at = timezone.now() + timedelta(hours=1)
        self.guardian.save(update_fields=["must_change_password", "temporary_password_expires_at"])
        old_version = self.guardian.token_version
        access, refresh = self.token_pair()
        self.bearer(access)
        response = self.client.post(self.change_password_url, {
            "current_password": self.password,
            "new_password": "EvenStronger!8492",
            "new_password_confirm": "EvenStronger!8492",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("access", response.data.get("data", {}))
        self.assertNotIn("refresh", response.data.get("data", {}))
        self.guardian.refresh_from_db()
        self.assertFalse(self.guardian.must_change_password)
        self.assertIsNone(self.guardian.temporary_password_expires_at)
        self.assertEqual(self.guardian.token_version, old_version + 1)
        self.assertEqual(self.client.get(self.me_url).status_code, 401)
        self.client.credentials()
        self.assertEqual(self.client.post(self.refresh_url, {"refresh": refresh}, format="json").status_code, 401)

    def test_change_password_validation(self):
        access, _ = self.token_pair()
        self.bearer(access)
        cases = (
            {"current_password": "wrong", "new_password": "EvenStronger!8492", "new_password_confirm": "EvenStronger!8492"},
            {"current_password": self.password, "new_password": "EvenStronger!8492", "new_password_confirm": "different"},
            {"current_password": self.password, "new_password": self.password, "new_password_confirm": self.password},
            {"current_password": self.password, "new_password": "123", "new_password_confirm": "123"},
        )
        for payload in cases:
            self.assertEqual(self.client.post(self.change_password_url, payload, format="json").status_code, 400)

    def test_permission_password_gate_is_reusable(self):
        request = APIRequestFactory().get("/future-mobile-api/")
        request.user = self.guardian
        request.auth = {"client": "mobile"}
        self.guardian.must_change_password = True
        permission = IsMobileGuardian()
        self.assertFalse(permission.has_permission(request, type("View", (), {})()))
        self.assertEqual(permission.message["code"], "PASSWORD_CHANGE_REQUIRED")
        allowed_view = type("View", (), {"allow_password_change_required": True})()
        self.assertTrue(IsMobileGuardian().has_permission(request, allowed_view))

    def test_throttle_scopes_are_independent(self):
        self.assertEqual(MobileLoginRateThrottle.scope, "mobile_login")
        self.assertEqual(WebLoginRateThrottle.scope, "web_login")

    def test_mobile_login_is_throttled(self):
        for expected in (401, 401, 401, 401, 401, 429):
            response = self.client.post(
                self.login_url,
                {"identifier": "rate-limited-user", "password": "wrong"},
                format="json",
                REMOTE_ADDR="192.0.2.44",
            )
            self.assertEqual(response.status_code, expected)
