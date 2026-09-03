import uuid
from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from notifications.models import Notification
from notifications.services import create_notification
from students.models import GuardianStudent, Student


User = get_user_model()


class CreateNotificationServiceTests(TestCase):
    def setUp(self):
        self.guardian = self.make_user("service-guardian", User.Role.GUARDIAN)
        self.other_guardian = self.make_user(
            "service-other-guardian", User.Role.GUARDIAN
        )
        self.student = self.make_student("Student")
        self.link = GuardianStudent.objects.create(
            guardian=self.guardian,
            student=self.student,
        )

    def make_user(self, username, role, **overrides):
        values = {
            "username": username,
            "password": "StrongPass!493",
            "role": role,
            "must_change_password": False,
        }
        values.update(overrides)
        return User.objects.create_user(**values)

    def make_student(self, first_name, **overrides):
        values = {
            "first_name": first_name,
            "last_name": "Family",
            "birth_date": date(2018, 1, 1),
            "gender": Student.Gender.MALE,
        }
        values.update(overrides)
        return Student.objects.create(**values)

    def create(self, **overrides):
        values = {
            "recipient": self.guardian,
            "notification_type": Notification.NotificationType.GENERAL,
            "title": "  Notification title  ",
            "body": "  Notification body  ",
        }
        values.update(overrides)
        return create_notification(**values)

    def test_creates_general_notification_and_returns_contract(self):
        notification, created = self.create()

        self.assertTrue(created)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(notification.recipient, self.guardian)
        self.assertEqual(notification.title, "Notification title")
        self.assertEqual(notification.body, "Notification body")
        self.assertIsNone(notification.student)
        self.assertEqual(notification.resource_type, "")
        self.assertIsNone(notification.resource_id)

    def test_creates_notification_for_active_owned_student(self):
        notification, created = self.create(student=self.student)
        self.assertTrue(created)
        self.assertEqual(notification.student, self.student)

    def test_missing_inactive_and_non_guardian_recipients_are_rejected(self):
        inactive = self.make_user(
            "service-inactive", User.Role.GUARDIAN, is_active=False
        )
        teacher = self.make_user("service-teacher", User.Role.TEACHER)
        for recipient in (None, inactive, teacher):
            with self.subTest(recipient=recipient):
                with self.assertRaises(ValidationError):
                    self.create(recipient=recipient)
        self.assertEqual(Notification.objects.count(), 0)

    def test_inactive_student_is_rejected(self):
        self.student.is_active = False
        self.student.save(update_fields=["is_active"])
        with self.assertRaises(ValidationError):
            self.create(student=self.student)

    def test_student_owned_by_another_guardian_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.create(recipient=self.other_guardian, student=self.student)

    def test_inactive_guardian_student_link_is_rejected(self):
        self.link.is_active = False
        self.link.save(update_fields=["is_active"])
        with self.assertRaises(ValidationError):
            self.create(student=self.student)

    def test_invalid_notification_type_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.create(notification_type="unknown")

    def test_blank_title_and_body_are_rejected(self):
        for field in ("title", "body"):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    self.create(**{field: "   "})

    def test_incomplete_and_invalid_resource_pairs_are_rejected(self):
        cases = (
            {"resource_type": "homework"},
            {"resource_id": uuid.uuid4()},
            {"resource_type": "homework", "resource_id": "not-a-uuid"},
        )
        for values in cases:
            with self.subTest(values=values):
                with self.assertRaises(ValidationError):
                    self.create(**values)

    def test_valid_resource_pair_is_normalized_and_saved(self):
        resource_id = uuid.uuid4()
        notification, created = self.create(
            resource_type="  homework  ",
            resource_id=str(resource_id),
        )
        self.assertTrue(created)
        self.assertEqual(notification.resource_type, "homework")
        self.assertEqual(notification.resource_id, resource_id)

    def test_null_event_key_allows_multiple_notifications(self):
        first, first_created = self.create()
        second, second_created = self.create()
        self.assertTrue(first_created)
        self.assertTrue(second_created)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(Notification.objects.count(), 2)

    def test_event_key_is_idempotent_and_preserves_original_data(self):
        first, first_created = self.create(
            event_key="appointment:1:approved",
            title="Approved",
            body="Original body",
        )
        second, second_created = self.create(
            event_key="appointment:1:approved",
            title="Rejected",
            body="Different body",
        )

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(second.id, first.id)
        self.assertEqual(second.title, "Approved")
        self.assertEqual(second.body, "Original body")
        self.assertEqual(Notification.objects.count(), 1)

    def test_same_event_key_for_different_guardian_is_allowed(self):
        first, first_created = self.create(event_key="general:shared")
        second, second_created = self.create(
            recipient=self.other_guardian,
            event_key="general:shared",
        )
        self.assertTrue(first_created)
        self.assertTrue(second_created)
        self.assertNotEqual(first.id, second.id)

    def test_database_constraint_remains_final_duplicate_defense(self):
        self.create(event_key="constraint:duplicate")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Notification.objects.create(
                recipient=self.guardian,
                notification_type=Notification.NotificationType.GENERAL,
                title="Bypass service",
                body="Direct duplicate",
                event_key="constraint:duplicate",
            )
