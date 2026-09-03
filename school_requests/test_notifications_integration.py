from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404 as django_get_object_or_404
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from notifications.models import Notification
from students.models import GuardianStudent, Student

from .models import SchoolRequest


User = get_user_model()


class SchoolRequestNotificationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.guardian = User.objects.create_user(
            username="request-notify-guardian", password="x",
            role=User.Role.GUARDIAN, must_change_password=False,
        )
        self.staff = User.objects.create_user(
            username="request-notify-staff", password="x",
            role=User.Role.SCHOOL_ADMIN, must_change_password=False,
        )
        self.student = Student.objects.create(
            first_name="Student", last_name="One", birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )
        GuardianStudent.objects.create(guardian=self.guardian, student=self.student)

    def create_request(self, student_marker=True):
        self.client.force_authenticate(self.guardian)
        payload = {"request_type": "inquiry", "details": "Private request"}
        if student_marker:
            payload["student"] = str(self.student.id)
        response = self.client.post("/api/v1/requests/", payload, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Notification.objects.count(), 0)
        return SchoolRequest.objects.get(pk=response.data["data"]["id"])

    def answer(self, school_request, text="Private school response"):
        self.client.force_authenticate(self.staff)
        return self.client.post(
            f"/api/v1/requests/{school_request.id}/answer/",
            {"school_response": text}, format="json",
        )

    @override_settings(FIREBASE_PUSH_ENABLED=True)
    @patch(
        "notifications.push_services.send_notification_push",
        side_effect=RuntimeError("Firebase unavailable"),
    )
    def test_answer_creates_private_deterministic_notification(self, _send):
        school_request = self.create_request()
        response_text = "Sensitive answer details"
        with self.captureOnCommitCallbacks(execute=True):
            response = self.answer(school_request, response_text)
        self.assertEqual(response.status_code, 200)
        school_request.refresh_from_db()
        self.assertEqual(school_request.status, SchoolRequest.Status.ANSWERED)
        self.assertEqual(school_request.school_response, response_text)
        self.assertEqual(school_request.handled_by, self.staff)
        self.assertIsNotNone(school_request.answered_at)
        notification = Notification.objects.get()
        self.assertEqual(notification.recipient, self.guardian)
        self.assertEqual(notification.student, self.student)
        self.assertEqual(notification.notification_type, "school_request")
        self.assertEqual(notification.resource_type, "school_request")
        self.assertEqual(notification.resource_id, school_request.id)
        self.assertEqual(notification.event_key, f"school_request:{school_request.id}:answered")
        self.assertNotIn(response_text, notification.body)

    def test_answer_locks_only_school_request_row(self):
        school_request = self.create_request()
        observed_lock_targets = []

        def inspect_lock(queryset, *args, **kwargs):
            observed_lock_targets.append(queryset.query.select_for_update_of)
            return django_get_object_or_404(queryset, *args, **kwargs)

        with patch("school_requests.views.get_object_or_404", side_effect=inspect_lock):
            response = self.answer(school_request, "Saved response")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(observed_lock_targets, [("self",)])

    def test_answer_without_student_is_supported(self):
        school_request = self.create_request(student_marker=False)
        self.assertEqual(self.answer(school_request).status_code, 200)
        self.assertIsNone(Notification.objects.get().student)

    def test_repeated_answer_does_not_duplicate(self):
        school_request = self.create_request()
        self.assertEqual(self.answer(school_request).status_code, 200)
        self.assertEqual(self.answer(school_request).status_code, 400)
        self.assertEqual(Notification.objects.count(), 1)

    def test_inactive_guardian_is_not_notified_but_answer_succeeds(self):
        school_request = self.create_request()
        self.guardian.is_active = False
        self.guardian.save(update_fields=["is_active"])
        self.assertEqual(self.answer(school_request).status_code, 200)
        self.assertEqual(Notification.objects.count(), 0)
