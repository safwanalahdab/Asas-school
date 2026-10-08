from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, GradeSubject, Section, Subject
from config.attachment_lifecycle_testing import AttachmentLifecycleTestsMixin
from teaching.models import TeacherAssignment

from .models import Homework


User = get_user_model()


class HomeworkAttachmentStorageSafetyTests(AttachmentLifecycleTestsMixin, TestCase):
    """New files never outlive a failed write; old files go only after commit."""

    model = Homework
    list_url = "/api/v1/homework/homeworks/"
    upload_dir = "homework/attachments"
    notify_path = "homework.views.notify_homework_created"

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="homework-storage-admin", password="StrongPass!493",
            role=User.Role.SCHOOL_ADMIN, must_change_password=False,
        )
        teacher = User.objects.create_user(
            username="homework-storage-teacher", password="StrongPass!493",
            role=User.Role.TEACHER, must_change_password=False,
        )
        year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1), end_date=date(2027, 6, 30), status=AcademicYear.Status.ACTIVE,
        )
        grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="Storage Grade")
        section = Section.objects.create(academic_year=year, grade_level=grade, name="A")
        grade_subject = GradeSubject.objects.create(
            academic_year=year, grade_level=grade, subject=Subject.objects.create(name="Storage Subject"),
        )
        self.assignment = TeacherAssignment.objects.create(
            teacher=teacher, grade_subject=grade_subject, section=section, start_date=date(2026, 9, 1),
        )
        self.client.force_authenticate(self.admin, token={"client": "web"})

    def create_payload(self):
        return {
            "teacher_assignment": str(self.assignment.id), "title": "Homework",
            "description": "Description", "homework_date": "2026-09-03",
            "due_date": "2026-09-04",
        }

    def create_existing(self, attachment):
        return Homework.objects.create(
            teacher_assignment=self.assignment, title="Legacy homework",
            description="Description", homework_date=date(2026, 9, 3),
            due_date=date(2026, 9, 4), attachment=attachment, created_by=self.admin,
        )
