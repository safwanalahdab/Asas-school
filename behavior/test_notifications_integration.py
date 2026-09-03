from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, Section
from notifications.models import Notification
from students.models import Enrollment, GuardianStudent, Student

from .models import BehaviorNote


User = get_user_model()


class BehaviorNotificationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.staff = User.objects.create_user(
            username="behavior-notify-staff", password="x",
            role=User.Role.SCHOOL_ADMIN, must_change_password=False,
        )
        self.guardian = User.objects.create_user(
            username="behavior-notify-guardian", password="x",
            role=User.Role.GUARDIAN, must_change_password=False,
        )
        year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1), end_date=date(2027, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )
        grade = GradeLevel.objects.create(stage="primary", name="Grade Behavior")
        section = Section.objects.create(
            academic_year=year, grade_level=grade, name="A"
        )
        self.student = Student.objects.create(
            first_name="Behavior", last_name="Student", birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )
        self.link = GuardianStudent.objects.create(
            guardian=self.guardian, student=self.student
        )
        self.enrollment = Enrollment.objects.create(
            student=self.student, academic_year=year, section=section,
            enrollment_date=date(2026, 9, 1),
        )

    def create_note(self, note_type, description="Sensitive behavior details"):
        self.client.force_authenticate(self.staff, token={"client": "web"})
        return self.client.post(
            "/api/v1/behavior/notes/",
            {
                "enrollment": str(self.enrollment.id), "note_type": note_type,
                "title": "Internal title", "description": description,
                "occurred_on": "2026-09-03",
            }, format="json",
        )

    def test_positive_and_negative_create_correct_notifications(self):
        for note_type in BehaviorNote.Type.values:
            with self.subTest(note_type=note_type):
                Notification.objects.all().delete()
                response = self.create_note(note_type)
                self.assertEqual(response.status_code, 201)
                note = BehaviorNote.objects.get(pk=response.data["data"]["id"])
                notification = Notification.objects.get()
                self.assertEqual(notification.recipient, self.guardian)
                self.assertEqual(notification.student, self.student)
                self.assertEqual(notification.resource_id, note.id)
                self.assertEqual(notification.event_key, f"behavior:{note.id}:created")

    def test_note_text_is_not_exposed(self):
        private_text = "Highly sensitive behavior note"
        self.assertEqual(self.create_note("negative", private_text).status_code, 201)
        self.assertNotIn(private_text, Notification.objects.get().body)

    def test_no_active_guardian_still_creates_note(self):
        self.link.is_active = False
        self.link.save(update_fields=["is_active"])
        response = self.create_note("positive")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(BehaviorNote.objects.count(), 1)
        self.assertEqual(Notification.objects.count(), 0)

    @override_settings(FIREBASE_PUSH_ENABLED=True)
    @patch(
        "notifications.push_services.send_notification_push",
        side_effect=RuntimeError("Firebase unavailable"),
    )
    def test_patch_does_not_create_second_notification(self, _send):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.create_note("positive")
        note_id = response.data["data"]["id"]
        self.assertEqual(Notification.objects.count(), 1)
        updated = self.client.patch(
            f"/api/v1/behavior/notes/{note_id}/",
            {"title": "Updated"}, format="json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(Notification.objects.count(), 1)
