import uuid
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from notifications.models import Notification
from students.models import GuardianStudent, Student


User = get_user_model()


class NotificationModelTests(TestCase):
    def setUp(self):
        self.guardian = self.create_guardian("guardian-one")
        self.other_guardian = self.create_guardian("guardian-two")
        self.student = self.create_student("أحمد")
        self.link = GuardianStudent.objects.create(
            guardian=self.guardian,
            student=self.student,
        )

    def create_guardian(self, username):
        return User.objects.create_user(
            username=username,
            password="Strong!934",
            role=User.Role.GUARDIAN,
            must_change_password=False,
        )

    def create_student(self, first_name, *, is_active=True):
        return Student.objects.create(
            first_name=first_name,
            last_name="خالد",
            birth_date=date(2018, 1, 1),
            gender=Student.Gender.MALE,
            is_active=is_active,
        )

    def make_notification(self, **overrides):
        values = {
            "recipient": self.guardian,
            "notification_type": Notification.NotificationType.GENERAL,
            "title": "إشعار",
            "body": "نص الإشعار",
        }
        values.update(overrides)
        return Notification(**values)

    def test_general_notification_defaults_without_student_or_resource(self):
        notification = self.make_notification()
        notification.full_clean()
        notification.save()

        self.assertFalse(notification.is_read)
        self.assertIsNone(notification.read_at)
        self.assertIsNone(notification.student)
        self.assertEqual(notification.resource_type, "")
        self.assertIsNone(notification.resource_id)

    def test_default_ordering_is_newest_first(self):
        older = self.make_notification(title="قديم")
        older.save()
        newer = self.make_notification(title="جديد")
        newer.save()
        Notification.objects.filter(pk=older.pk).update(
            created_at=newer.created_at - timedelta(minutes=1)
        )

        self.assertEqual(list(Notification.objects.all()), [newer, older])

    def test_notification_types_are_complete(self):
        self.assertEqual(
            {value for value, _label in Notification.NotificationType.choices},
            {
                "homework", "announcement", "grades", "attendance",
                "behavior", "finance", "school_request", "appointment",
                "general",
            },
        )

    def test_active_owned_student_is_valid(self):
        self.make_notification(student=self.student).full_clean()

    def test_student_owned_by_another_guardian_is_invalid(self):
        notification = self.make_notification(
            recipient=self.other_guardian,
            student=self.student,
        )
        with self.assertRaises(ValidationError):
            notification.full_clean()

    def test_inactive_guardian_student_link_is_invalid(self):
        self.link.is_active = False
        self.link.save(update_fields=["is_active"])
        with self.assertRaises(ValidationError):
            self.make_notification(student=self.student).full_clean()

    def test_inactive_student_is_invalid(self):
        self.student.is_active = False
        self.student.save(update_fields=["is_active"])
        with self.assertRaises(ValidationError):
            self.make_notification(student=self.student).full_clean()

    def test_same_recipient_and_event_key_cannot_repeat(self):
        self.make_notification(event_key="homework:created:1").save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_notification(event_key="homework:created:1").save()

    def test_same_event_key_for_another_recipient_is_allowed(self):
        self.make_notification(event_key="announcement:1").save()
        self.make_notification(
            recipient=self.other_guardian,
            event_key="announcement:1",
        ).save()

    def test_null_event_key_can_repeat_for_same_recipient(self):
        self.make_notification().save()
        self.make_notification().save()
        self.assertEqual(Notification.objects.count(), 2)

    def test_valid_resource_pair_is_allowed(self):
        notification = self.make_notification(
            resource_type="homework",
            resource_id=uuid.uuid4(),
        )
        notification.full_clean()
        notification.save()

    def test_resource_type_without_id_is_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_notification(resource_type="homework").save()

    def test_resource_id_without_type_is_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_notification(resource_id=uuid.uuid4()).save()

    def test_unread_notification_cannot_have_read_at(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_notification(read_at=timezone.now()).save()

    def test_read_notification_requires_read_at(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_notification(is_read=True).save()
