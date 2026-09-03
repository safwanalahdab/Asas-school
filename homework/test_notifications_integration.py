from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, GradeSubject, Section, Subject
from notifications.models import Notification
from students.models import Enrollment, GuardianStudent, Student
from teaching.models import TeacherAssignment

from .models import Homework
from .services import notify_homework_created


User = get_user_model()


class HomeworkNotificationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="homework-notify-admin", password="x",
            role=User.Role.SCHOOL_ADMIN, must_change_password=False,
        )
        self.guardian = self.user("homework-notify-guardian")
        self.other_guardian = self.user("homework-notify-other")
        self.year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1), end_date=date(2027, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )
        self.grade = GradeLevel.objects.create(stage="primary", name="Grade H")
        self.section = Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name="A"
        )
        self.other_section = Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name="B"
        )
        subject = Subject.objects.create(name="Homework subject")
        grade_subject = GradeSubject.objects.create(
            academic_year=self.year, grade_level=self.grade, subject=subject
        )
        self.assignment = TeacherAssignment.objects.create(
            teacher=self.admin, grade_subject=grade_subject, section=self.section,
            start_date=date(2026, 9, 1),
        )
        self.target = self.child("Target", self.guardian, self.section)
        self.outside = self.child("Outside", self.other_guardian, self.other_section)

    def user(self, username):
        return User.objects.create_user(
            username=username, password="x", role=User.Role.GUARDIAN,
            must_change_password=False,
        )

    def child(self, name, guardian, section, *, link_active=True):
        student = Student.objects.create(
            first_name=name, last_name="Child", birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )
        GuardianStudent.objects.create(
            guardian=guardian, student=student, is_active=link_active
        )
        Enrollment.objects.create(
            student=student, academic_year=self.year, section=section,
            enrollment_date=date(2026, 9, 1),
        )
        return student

    def create_homework(self):
        return Homework.objects.create(
            teacher_assignment=self.assignment, title="Secret homework title",
            description="Sensitive full homework description",
            homework_date=date(2026, 9, 3), due_date=date(2026, 9, 4),
            created_by=self.admin,
        )

    def test_target_section_only_and_payload_is_student_specific(self):
        homework = self.create_homework()
        notify_homework_created(homework)
        notification = Notification.objects.get()
        self.assertEqual(notification.recipient, self.guardian)
        self.assertEqual(notification.student, self.target)
        self.assertEqual(notification.resource_id, homework.id)
        self.assertEqual(notification.event_key, f"homework:{homework.id}:student:{self.target.id}")
        self.assertNotIn(homework.description, notification.body)
        self.assertFalse(Notification.objects.filter(recipient=self.other_guardian).exists())

    def test_inactive_relation_and_guardian_are_excluded(self):
        self.target.guardian_link.is_active = False
        self.target.guardian_link.save(update_fields=["is_active"])
        homework = self.create_homework()
        notify_homework_created(homework)
        self.assertEqual(Notification.objects.count(), 0)

    def test_two_target_children_of_one_guardian_do_not_collide(self):
        second = self.child("Second", self.guardian, self.section)
        homework = self.create_homework()
        notify_homework_created(homework)
        self.assertEqual(Notification.objects.count(), 2)
        self.assertEqual(
            set(Notification.objects.values_list("student_id", flat=True)),
            {self.target.id, second.id},
        )

    @override_settings(FIREBASE_PUSH_ENABLED=True)
    @patch(
        "notifications.push_services.send_notification_push",
        side_effect=RuntimeError("Firebase unavailable"),
    )
    def test_api_create_triggers_once_and_patch_does_not_notify_again(self, _send):
        self.client.force_authenticate(self.admin, token={"client": "web"})
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/v1/homework/homeworks/",
                {
                    "teacher_assignment": str(self.assignment.id), "title": "Homework",
                    "description": "Private", "homework_date": "2026-09-03",
                    "due_date": "2026-09-04",
                }, format="json",
            )
        self.assertEqual(response.status_code, 201)
        homework_id = response.data["data"]["id"]
        self.assertEqual(Notification.objects.count(), 1)
        patch_response = self.client.patch(
            f"/api/v1/homework/homeworks/{homework_id}/",
            {"title": "Updated"}, format="json",
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(Notification.objects.count(), 1)
