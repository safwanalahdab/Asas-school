from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from accounts.models import User
from accounts.serializers import (
    EMAIL_MATCHES_USERNAME,
    EMAIL_TAKEN,
    USERNAME_MATCHES_EMAIL,
    USERNAME_TAKEN,
    translate_identity_integrity_errors,
)


def skip_email_check(*args, **kwargs):
    """Simulate a concurrent request that passed validation before ours saved."""


skip_username_check = skip_email_check


class AccountUniquenessApiTestMixin:
    users_url = "/api/v1/accounts/users/"
    me_url = "/api/v1/auth/web/me/"
    password = "UniqueStrong!934"

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.admin = self.make_user("uniqueness-admin", User.Role.SCHOOL_ADMIN)
        self.admin.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="accounts",
            codename__in=("add_user", "change_user", "view_user"),
        ))
        self.owner = self.make_user(
            "uniqueness-owner", User.Role.TEACHER, email="owner@example.com"
        )
        self.other = self.make_user(
            "uniqueness-other", User.Role.TEACHER, email="other@example.com"
        )
        self.client.force_authenticate(self.admin, token={"client": "web"})

    def make_user(self, username, role, **kwargs):
        return User.objects.create_user(
            username=username,
            password=self.password,
            role=role,
            must_change_password=False,
            **kwargs,
        )

    def create(self, **payload):
        payload.setdefault("role", User.Role.TEACHER)
        return self.client.post(self.users_url, payload, format="json")

    def patch_user(self, user, **payload):
        return self.client.patch(
            f"{self.users_url}{user.pk}/", payload, format="json"
        )

    def assert_field_error(self, response, field, message):
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "VALIDATION_ERROR")
        self.assertEqual(response.data["errors"][field], [message])


class EmailUniquenessApiTests(AccountUniquenessApiTestMixin, TestCase):
    def test_create_with_existing_email_is_rejected_in_any_case(self):
        for index, email in enumerate(
            ("owner@example.com", "OWNER@Example.COM", "Owner@example.com")
        ):
            with self.subTest(email=email):
                response = self.create(username=f"new-user-{index}", email=email)
                self.assert_field_error(response, "email", EMAIL_TAKEN)
        self.assertFalse(User.objects.filter(username__startswith="new-user-").exists())

    def test_update_to_another_accounts_email_is_rejected(self):
        for email in ("other@example.com", "OTHER@example.com"):
            with self.subTest(email=email):
                response = self.patch_user(self.owner, email=email)
                self.assert_field_error(response, "email", EMAIL_TAKEN)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.email, "owner@example.com")

    def test_update_keeping_own_email_is_allowed(self):
        for email in ("owner@example.com", "OWNER@example.com"):
            with self.subTest(email=email):
                response = self.patch_user(self.owner, email=email)
                self.assertEqual(response.status_code, 200, response.data)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.email, "OWNER@example.com")

    def test_blank_and_null_email_are_allowed_for_many_accounts(self):
        for index, email in enumerate(("", "", None, None)):
            with self.subTest(index=index, email=email):
                response = self.create(username=f"no-email-{index}", email=email)
                self.assertEqual(response.status_code, 201, response.data)
        for email in ("", None):
            with self.subTest(update_email=email):
                response = self.patch_user(self.owner, email=email)
                self.assertEqual(response.status_code, 200, response.data)
                response = self.patch_user(self.other, email=email)
                self.assertEqual(response.status_code, 200, response.data)

    def test_create_race_with_database_constraint_returns_400(self):
        with patch("accounts.serializers.ensure_email_available", skip_email_check):
            response = self.create(username="race-create", email="OWNER@example.com")
        self.assert_field_error(response, "email", EMAIL_TAKEN)
        self.assertFalse(User.objects.filter(username="race-create").exists())

    def test_update_race_with_database_constraint_returns_400(self):
        with patch("accounts.serializers.ensure_email_available", skip_email_check):
            response = self.patch_user(
                self.owner, first_name="Changed", email="OTHER@example.com"
            )
        self.assert_field_error(response, "email", EMAIL_TAKEN)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.email, "owner@example.com")
        self.assertEqual(self.owner.first_name, "")

    def test_web_me_race_with_database_constraint_returns_400(self):
        self.client.force_authenticate(self.owner, token={"client": "web"})
        with patch("accounts.serializers.ensure_email_available", skip_email_check):
            response = self.client.patch(
                self.me_url, {"email": "OTHER@example.com"}, format="json"
            )
        self.assert_field_error(response, "email", EMAIL_TAKEN)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.email, "owner@example.com")


class UsernameUniquenessApiTests(AccountUniquenessApiTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.ahmad = self.make_user("Ahmad", User.Role.TEACHER)

    def test_create_with_existing_username_in_other_case_is_rejected(self):
        for username in ("ahmad", "AHMAD", "aHmAd"):
            with self.subTest(username=username):
                response = self.create(username=username)
                self.assert_field_error(response, "username", USERNAME_TAKEN)
        self.assertEqual(User.objects.filter(username__iexact="ahmad").count(), 1)

    def test_update_to_existing_username_in_other_case_is_rejected(self):
        response = self.patch_user(self.owner, username="AHMAD")
        self.assert_field_error(response, "username", USERNAME_TAKEN)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.username, "uniqueness-owner")

    def test_account_may_change_case_of_its_own_username(self):
        response = self.patch_user(self.ahmad, username="ahmad")
        self.assertEqual(response.status_code, 200, response.data)
        self.ahmad.refresh_from_db()
        self.assertEqual(self.ahmad.username, "ahmad")

    def test_username_is_stored_as_typed(self):
        response = self.create(username="MiXeD-Case")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(User.objects.filter(username="MiXeD-Case").exists())

    def test_username_matching_another_accounts_email_is_rejected(self):
        response = self.create(username="OTHER@example.com")
        self.assert_field_error(response, "username", USERNAME_MATCHES_EMAIL)
        response = self.patch_user(self.owner, username="Other@Example.com")
        self.assert_field_error(response, "username", USERNAME_MATCHES_EMAIL)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.username, "uniqueness-owner")

    def test_email_matching_another_accounts_username_is_rejected(self):
        self.make_user("shared@example.com", User.Role.TEACHER)
        response = self.create(username="new-user", email="SHARED@example.com")
        self.assert_field_error(response, "email", EMAIL_MATCHES_USERNAME)
        response = self.patch_user(self.owner, email="Shared@Example.com")
        self.assert_field_error(response, "email", EMAIL_MATCHES_USERNAME)
        self.client.force_authenticate(self.owner, token={"client": "web"})
        response = self.client.patch(
            self.me_url, {"email": "shared@EXAMPLE.com"}, format="json"
        )
        self.assert_field_error(response, "email", EMAIL_MATCHES_USERNAME)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.email, "owner@example.com")

    def test_own_username_and_email_may_match(self):
        response = self.patch_user(self.owner, username="OWNER@example.com")
        self.assertEqual(response.status_code, 200, response.data)
        self.client.force_authenticate(self.other, token={"client": "web"})
        self.other.username = "other-self@example.com"
        self.other.save(update_fields=["username"])
        response = self.client.patch(
            self.me_url, {"email": "Other-Self@example.com"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_create_race_with_username_constraint_returns_400(self):
        with patch(
            "accounts.serializers.ensure_username_available", skip_username_check
        ):
            response = self.create(username="AHMAD")
        self.assert_field_error(response, "username", USERNAME_TAKEN)
        self.assertEqual(User.objects.filter(username__iexact="ahmad").count(), 1)

    def test_update_race_with_username_constraint_returns_400(self):
        with patch(
            "accounts.serializers.ensure_username_available", skip_username_check
        ):
            response = self.patch_user(self.owner, username="aHMAD")
        self.assert_field_error(response, "username", USERNAME_TAKEN)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.username, "uniqueness-owner")

    def test_database_rejects_username_differing_only_by_case(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username="AHMAD", role=User.Role.TEACHER)
        self.assertEqual(User.objects.filter(username__iexact="ahmad").count(), 1)


class LoginIdentifierCaseTests(TestCase):
    password = "LoginCase!934"

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.decoy = User.objects.create_user(
            username="Other.Login", email="other.login@example.com",
            password=self.password, role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
        )

    def assert_login_finds(self, url, user, identifiers):
        for identifier in identifiers:
            with self.subTest(identifier=identifier):
                cache.clear()
                response = self.client.post(
                    url,
                    {"identifier": identifier, "password": self.password},
                    format="json",
                )
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(
                    str(response.data["data"]["user"]["id"]), str(user.pk)
                )

    def test_web_login_finds_account_in_any_case(self):
        user = User.objects.create_user(
            username="Ahmad.Login", email="ahmad.login@example.com",
            password=self.password, role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
        )
        self.assert_login_finds(
            "/api/v1/auth/web/login/",
            user,
            ("Ahmad.Login", "ahmad.login", "AHMAD.LOGIN", "AHMAD.LOGIN@EXAMPLE.COM"),
        )

    def test_mobile_login_finds_account_in_any_case(self):
        guardian = User.objects.create_user(
            username="Guardian.Login", email="guardian.login@example.com",
            password=self.password, role=User.Role.GUARDIAN,
            must_change_password=False,
        )
        self.assert_login_finds(
            "/api/v1/auth/mobile/login/",
            guardian,
            (
                "Guardian.Login", "guardian.login", "GUARDIAN.LOGIN",
                "Guardian.Login@Example.com",
            ),
        )


class TranslateIdentityIntegrityErrorsTests(TestCase):
    def test_other_constraint_violation_is_not_translated(self):
        User.objects.create_user(
            username="national-id-one", national_id="555555555555",
            role=User.Role.TEACHER,
        )
        with self.assertRaises(IntegrityError):
            with translate_identity_integrity_errors():
                User.objects.create_user(
                    username="national-id-two", national_id="555555555555",
                    role=User.Role.TEACHER,
                )
        # The savepoint keeps the surrounding transaction usable.
        self.assertEqual(User.objects.filter(national_id="555555555555").count(), 1)

    def test_driver_constraint_name_is_used_when_available(self):
        cause = Exception("driver error")
        cause.diag = SimpleNamespace(
            constraint_name="unique_user_email_case_insensitive"
        )
        with self.assertRaises(ValidationError) as caught:
            with translate_identity_integrity_errors():
                raise IntegrityError("duplicate key value") from cause
        self.assertEqual(caught.exception.detail, {"email": [EMAIL_TAKEN]})

    def test_driver_constraint_name_takes_precedence_over_message(self):
        cause = Exception("driver error")
        cause.diag = SimpleNamespace(constraint_name="accounts_user_national_id_key")
        with self.assertRaises(IntegrityError):
            with translate_identity_integrity_errors():
                raise IntegrityError(
                    "unique_user_email_case_insensitive mentioned in text"
                ) from cause
