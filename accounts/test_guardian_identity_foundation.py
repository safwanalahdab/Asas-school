from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import TestCase


User = get_user_model()
backfill_guardian_national_ids = import_module(
    "accounts.migrations.0006_backfill_guardian_national_ids"
).backfill_guardian_national_ids


class GuardianIdentityFoundationTests(TestCase):
    def create_user(self, username, role=User.Role.GUARDIAN, **extra_fields):
        return User.objects.create_user(
            username=username,
            password="Strong!934",
            role=role,
            must_change_password=False,
            **extra_fields,
        )

    def run_backfill(self):
        schema_editor = SimpleNamespace(connection=connection)
        backfill_guardian_national_ids(apps, schema_editor)

    def test_user_can_store_national_id(self):
        user = self.create_user("guardian-national", national_id="01234567890")

        user.refresh_from_db()

        self.assertEqual(user.national_id, "01234567890")

    def test_user_can_store_phone_number(self):
        user = self.create_user("guardian-phone", phone_number="0999999999")

        user.refresh_from_db()

        self.assertEqual(user.phone_number, "0999999999")

    def test_national_id_is_unique(self):
        self.create_user("guardian-one", national_id="111222333")

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_user("guardian-two", national_id="111222333")

    def test_multiple_users_can_have_null_national_id(self):
        first = self.create_user("guardian-null-one")
        second = self.create_user("guardian-null-two")

        self.assertIsNone(first.national_id)
        self.assertIsNone(second.national_id)

    def test_numeric_guardian_username_is_backfilled(self):
        guardian = self.create_user("01234567890")

        self.run_backfill()

        guardian.refresh_from_db()
        self.assertEqual(guardian.national_id, guardian.username)

    def test_non_numeric_guardian_username_is_not_backfilled(self):
        guardian = self.create_user("guardian-legacy")

        self.run_backfill()

        guardian.refresh_from_db()
        self.assertIsNone(guardian.national_id)

    def test_non_guardian_numeric_username_is_not_backfilled(self):
        teacher = self.create_user("987654321", role=User.Role.TEACHER)

        self.run_backfill()

        teacher.refresh_from_db()
        self.assertIsNone(teacher.national_id)

    def test_backfill_preserves_identity_and_security_fields(self):
        guardian = self.create_user("123456789", phone_number="0988888888")
        original_values = {
            "username": guardian.username,
            "password": guardian.password,
            "role": guardian.role,
            "token_version": guardian.token_version,
        }

        self.run_backfill()

        guardian.refresh_from_db()
        self.assertEqual(
            {
                "username": guardian.username,
                "password": guardian.password,
                "role": guardian.role,
                "token_version": guardian.token_version,
            },
            original_values,
        )
