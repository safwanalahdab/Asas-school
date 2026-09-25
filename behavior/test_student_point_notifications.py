from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User
from academics.models import AcademicYear, GradeLevel, Section
from notifications.models import Notification
from students.models import Enrollment, GuardianStudent, Student

from .models import StudentPointEntry
from .services import notify_student_point_entry_created


class StudentPointNotificationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.staff = self.make_user(
            "point-notification-staff",
            User.Role.SCHOOL_ADMIN,
        )
        self.guardian = self.make_user(
            "point-notification-guardian",
            User.Role.GUARDIAN,
        )
        self.other_guardian = self.make_user(
            "point-notification-other",
            User.Role.GUARDIAN,
        )
        self.staff.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="behavior",
            codename__in=(
                "add_studentpointentry",
                "change_studentpointentry",
                "delete_studentpointentry",
            ),
        ))
        self.year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )
        self.grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY,
            name="Point notification grade",
        )
        self.section = Section.objects.create(
            academic_year=self.year,
            grade_level=self.grade,
            name="A",
        )
        self.student = self.make_student("Ahmad", "Mohammad")
        self.other_student = self.make_student("Other", "Family")
        self.link = GuardianStudent.objects.create(
            guardian=self.guardian,
            student=self.student,
            is_active=True,
        )
        GuardianStudent.objects.create(
            guardian=self.other_guardian,
            student=self.other_student,
            is_active=True,
        )
        self.enrollment = Enrollment.objects.create(
            student=self.student,
            academic_year=self.year,
            section=self.section,
            enrollment_date=self.year.start_date,
        )
        self.client.force_authenticate(self.staff, token={"client": "web"})

    @staticmethod
    def make_user(username, role):
        return User.objects.create_user(
            username=username,
            password="StrongPass!493",
            role=role,
            must_change_password=False,
        )

    @staticmethod
    def make_student(first_name, last_name):
        return Student.objects.create(
            first_name=first_name,
            last_name=last_name,
            birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )

    def payload(self):
        return {
            "enrollment": str(self.enrollment.pk),
            "points": 10,
            "note": "مشاركة مميزة",
            "occurred_on": "2026-09-03",
        }

    def create_point(self):
        return self.client.post(
            "/api/v1/behavior/points/",
            self.payload(),
            format="json",
        )

    def test_create_point_notifies_correct_guardian_with_safe_navigation_data(self):
        response = self.create_point()
        self.assertEqual(response.status_code, 201)
        point = StudentPointEntry.objects.get(pk=response.data["data"]["id"])
        notification = Notification.objects.get()
        self.assertEqual(notification.recipient, self.guardian)
        self.assertEqual(notification.student, self.student)
        self.assertEqual(notification.notification_type, Notification.NotificationType.BEHAVIOR)
        self.assertEqual(notification.resource_type, "student_points")
        self.assertEqual(notification.resource_id, point.pk)
        self.assertEqual(notification.event_key, f"student_points:{point.pk}:created")
        self.assertIn("10", notification.body)
        self.assertIn(self.student.full_name, notification.body)

    def test_guardian_from_another_family_is_not_notified(self):
        self.assertEqual(self.create_point().status_code, 201)
        self.assertFalse(Notification.objects.filter(recipient=self.other_guardian).exists())

    def test_inactive_guardian_relationship_is_not_notified(self):
        self.link.is_active = False
        self.link.save(update_fields=["is_active"])
        self.assertEqual(self.create_point().status_code, 201)
        self.assertEqual(Notification.objects.count(), 0)

    def test_inactive_guardian_user_is_not_notified(self):
        self.guardian.is_active = False
        self.guardian.save(update_fields=["is_active"])
        self.assertEqual(self.create_point().status_code, 201)
        self.assertEqual(Notification.objects.count(), 0)

    @patch("behavior.services.create_notification")
    @patch("behavior.services.GuardianStudent.objects.select_related")
    def test_service_notifies_every_eligible_guardian_returned_by_recipient_query(
        self,
        select_related,
        create_notification,
    ):
        second_guardian = self.make_user(
            "point-notification-second-eligible",
            User.Role.GUARDIAN,
        )
        select_related.return_value.filter.return_value = [
            SimpleNamespace(guardian=self.guardian),
            SimpleNamespace(guardian=second_guardian),
        ]
        first_notification = SimpleNamespace(id="first")
        second_notification = SimpleNamespace(id="second")
        create_notification.side_effect = [
            (first_notification, True),
            (second_notification, True),
        ]
        point = StudentPointEntry.objects.create(
            enrollment=self.enrollment,
            points=10,
            note="Service coverage",
            occurred_on=date(2026, 9, 3),
            created_by=self.staff,
        )

        result = notify_student_point_entry_created(point)

        self.assertEqual(result, [first_notification, second_notification])
        self.assertEqual(create_notification.call_count, 2)
        self.assertEqual(
            [call.kwargs["recipient"] for call in create_notification.call_args_list],
            [self.guardian, second_guardian],
        )

    def test_missing_guardian_does_not_block_point_creation(self):
        self.link.delete()
        response = self.create_point()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(StudentPointEntry.objects.count(), 1)
        self.assertEqual(Notification.objects.count(), 0)

    def test_patch_does_not_create_notification(self):
        response = self.create_point()
        point_id = response.data["data"]["id"]
        self.assertEqual(Notification.objects.count(), 1)
        updated = self.client.patch(
            f"/api/v1/behavior/points/{point_id}/",
            {"points": 20},
            format="json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(Notification.objects.count(), 1)

    def test_delete_does_not_create_notification(self):
        response = self.create_point()
        point_id = response.data["data"]["id"]
        self.assertEqual(Notification.objects.count(), 1)
        deleted = self.client.delete(f"/api/v1/behavior/points/{point_id}/")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(Notification.objects.count(), 1)

    @override_settings(FIREBASE_PUSH_ENABLED=True)
    @patch(
        "notifications.push_services.send_notification_push",
        side_effect=RuntimeError("Firebase unavailable"),
    )
    def test_push_failure_does_not_block_point_creation(self, _send):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.create_point()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(StudentPointEntry.objects.count(), 1)
        self.assertEqual(Notification.objects.count(), 1)

    def test_single_post_creates_one_notification_and_keeps_response_contract(self):
        response = self.create_point()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(response.data["code"], "STUDENT_POINT_CREATED")
        self.assertEqual(
            set(response.data),
            {"success", "code", "message", "data", "meta"},
        )
        self.assertNotIn("notification", response.data["data"])
