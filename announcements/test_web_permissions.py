from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, GradeSubject, Section, Subject
from teaching.models import TeacherAssignment
from students.models import Enrollment, GuardianStudent, Student

from .models import Announcement


User = get_user_model()


class AnnouncementWebPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = self.user("announce-admin", User.Role.SCHOOL_ADMIN)
        self.teacher = self.user("announce-teacher", User.Role.TEACHER)
        self.guardian = self.user("announce-guardian", User.Role.GUARDIAN)
        self.admin.user_permissions.clear()
        self.teacher.user_permissions.clear()
        self.today = timezone.localdate()
        year = AcademicYear.objects.create(
            start_date=self.today - timedelta(days=100), end_date=self.today + timedelta(days=100),
            status=AcademicYear.Status.ACTIVE,
        )
        grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="Announcement grade")
        self.section = Section.objects.create(academic_year=year, grade_level=grade, name="A")
        self.other_section = Section.objects.create(academic_year=year, grade_level=grade, name="B")
        student = Student.objects.create(
            first_name="Announcement", last_name="Child",
            birth_date=date(2015, 1, 1), gender=Student.Gender.MALE,
        )
        GuardianStudent.objects.create(guardian=self.guardian, student=student)
        Enrollment.objects.create(
            student=student, academic_year=year, section=self.section,
            enrollment_date=self.today - timedelta(days=10),
        )
        subject = Subject.objects.create(name="Announcement subject")
        grade_subject = GradeSubject.objects.create(academic_year=year, grade_level=grade, subject=subject)
        TeacherAssignment.objects.create(
            teacher=self.teacher, grade_subject=grade_subject, section=self.section,
            start_date=self.today - timedelta(days=10),
        )
        self.own = self.announcement(self.section)
        self.other = self.announcement(self.other_section)
        self.future = self.announcement(self.section, publish_date=self.today + timedelta(days=1))

    def user(self, name, role):
        return User.objects.create_user(username=name, password="StrongPass!123", role=role, must_change_password=False)

    def grant(self, user, code):
        app, codename = code.split(".")
        user.user_permissions.add(Permission.objects.get(content_type__app_label=app, codename=codename))

    def announcement(self, section, publish_date=None):
        item = Announcement.objects.create(
            scope=Announcement.Scope.SECTIONS, title="Notice", content="Content",
            publish_date=publish_date or self.today, created_by=self.admin,
        )
        item.sections.add(section)
        return item

    def test_teacher_view_permission_preserves_assignment_and_date_scope(self):
        url = "/api/v1/announcements/"
        self.client.force_authenticate(self.teacher)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.grant(self.teacher, "announcements.view_announcement")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["data"]["results"]], [str(self.own.pk)])
        self.assertEqual(self.client.get(f"{url}{self.own.pk}/").status_code, 200)
        self.assertEqual(self.client.get(f"{url}{self.other.pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"{url}{self.future.pk}/").status_code, 404)
        self.assertEqual(self.client.get(url, {"section": str(self.other_section.pk)}).data["data"]["results"], [])

    def test_create_change_delete_permissions_are_separate(self):
        url = "/api/v1/announcements/"
        detail = f"{url}{self.own.pk}/"
        tech = self.user("announce-tech", User.Role.TECH_SUPPORT)
        self.client.force_authenticate(tech)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.grant(tech, "announcements.view_announcement")
        self.assertEqual(self.client.get(f"{url}{self.other.pk}/").status_code, 200)
        payload = {
            "scope": "all", "title": "New", "content": "Content",
            "publish_date": str(self.today),
        }
        self.assertEqual(self.client.post(url, payload).status_code, 403)
        self.grant(tech, "announcements.add_announcement")
        self.assertEqual(self.client.post(url, payload).status_code, 201)
        self.assertEqual(self.client.patch(detail, {"title": "Changed"}).status_code, 403)
        self.grant(tech, "announcements.change_announcement")
        self.assertEqual(self.client.patch(detail, {"title": "Changed"}).status_code, 200)
        self.assertEqual(self.client.delete(detail).status_code, 403)
        self.grant(tech, "announcements.delete_announcement")
        self.assertEqual(self.client.delete(detail).status_code, 200)

    def test_admin_revocation_superuser_and_unsupported_method(self):
        url = "/api/v1/announcements/"
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(url).status_code, 403)
        root = User.objects.create_superuser(username="announce-root", password="StrongPass!123")
        self.client.force_authenticate(root)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.put(f"{url}{self.own.pk}/", {}).status_code, 405)

    def test_guardian_direct_permission_keeps_enrollment_scope(self):
        url = "/api/v1/announcements/"
        self.client.force_authenticate(self.guardian)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.grant(self.guardian, "announcements.view_announcement")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["data"]["results"]], [str(self.own.pk)])
        self.assertEqual(self.client.get(f"{url}{self.other.pk}/").status_code, 404)
