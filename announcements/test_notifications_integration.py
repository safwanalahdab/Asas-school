from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, Section
from notifications.models import Notification
from students.models import Enrollment, GuardianStudent, Student

from .models import Announcement
from .services import notify_announcement_published


User = get_user_model()


class AnnouncementNotificationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.today = timezone.localdate()
        self.admin = self.user("announcement-notify-admin", User.Role.SCHOOL_ADMIN)
        self.guardian = self.user("announcement-notify-guardian", User.Role.GUARDIAN)
        self.other_guardian = self.user("announcement-notify-other", User.Role.GUARDIAN)
        self.year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1), end_date=date(2027, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )
        self.grade = GradeLevel.objects.create(stage="primary", name="Grade A")
        self.other_grade = GradeLevel.objects.create(stage="primary", name="Grade B")
        self.section = Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name="A"
        )
        self.other_section = Section.objects.create(
            academic_year=self.year, grade_level=self.other_grade, name="B"
        )
        self.child("One", self.guardian, self.section)
        self.child("Two", self.guardian, self.section)
        self.child("Other", self.other_guardian, self.other_section)

    def user(self, username, role):
        return User.objects.create_user(
            username=username, password="x", role=role, must_change_password=False
        )

    def child(self, name, guardian, section):
        student = Student.objects.create(
            first_name=name, last_name="Child", birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )
        GuardianStudent.objects.create(guardian=guardian, student=student)
        Enrollment.objects.create(
            student=student, academic_year=self.year, section=section,
            enrollment_date=date(2026, 9, 1),
        )

    def announcement(self, scope, publish_date=None):
        return Announcement.objects.create(
            scope=scope, title="Private original title",
            content="Sensitive complete announcement content",
            publish_date=publish_date or self.today, created_by=self.admin,
        )

    def test_all_scope_deduplicates_guardian_with_multiple_children(self):
        announcement = self.announcement(Announcement.Scope.ALL)
        notify_announcement_published(announcement)
        self.assertEqual(Notification.objects.count(), 2)
        self.assertEqual(
            set(Notification.objects.values_list("recipient_id", flat=True)),
            {self.guardian.id, self.other_guardian.id},
        )

    def test_grade_and_section_scopes_exclude_unrelated_guardians(self):
        for scope in (Announcement.Scope.GRADES, Announcement.Scope.SECTIONS):
            with self.subTest(scope=scope):
                Notification.objects.all().delete()
                announcement = self.announcement(scope)
                if scope == Announcement.Scope.GRADES:
                    announcement.grade_levels.add(self.grade)
                else:
                    announcement.sections.add(self.section)
                notify_announcement_published(announcement)
                notification = Notification.objects.get()
                self.assertEqual(notification.recipient, self.guardian)
                self.assertEqual(notification.resource_id, announcement.id)
                self.assertEqual(
                    notification.event_key,
                    f"announcement:{announcement.id}:published",
                )
                self.assertNotIn(announcement.content, notification.body)

    def test_future_announcement_is_deferred_without_notification(self):
        announcement = self.announcement(
            Announcement.Scope.ALL, self.today + timedelta(days=1)
        )
        self.assertEqual(notify_announcement_published(announcement), [])
        self.assertEqual(Notification.objects.count(), 0)

    @override_settings(FIREBASE_PUSH_ENABLED=True)
    @patch(
        "notifications.push_services.send_notification_push",
        side_effect=RuntimeError("Firebase unavailable"),
    )
    def test_api_create_notifies_and_patch_does_not_duplicate(self, _send):
        self.client.force_authenticate(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/v1/announcements/",
                {
                    "scope": "sections", "sections": [str(self.section.id)],
                    "grade_levels": [], "title": "Announcement", "content": "Private",
                    "publish_date": str(self.today),
                }, format="json",
            )
        self.assertEqual(response.status_code, 201)
        announcement_id = response.data["data"]["id"]
        self.assertEqual(Notification.objects.count(), 1)
        updated = self.client.patch(
            f"/api/v1/announcements/{announcement_id}/",
            {"title": "Updated"}, format="json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(Notification.objects.count(), 1)
