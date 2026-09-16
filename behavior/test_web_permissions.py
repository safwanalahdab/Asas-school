from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, Section
from students.models import Enrollment, Student

from .models import BehaviorNote


User = get_user_model()


class BehaviorWebPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = self.user("behavior-admin", User.Role.SCHOOL_ADMIN)
        self.teacher = self.user("behavior-teacher", User.Role.TEACHER)
        self.admin.user_permissions.clear()
        self.teacher.user_permissions.clear()
        year = AcademicYear.objects.create(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="Behavior grade")
        section = Section.objects.create(academic_year=year, grade_level=grade, name="A")
        student = Student.objects.create(
            first_name="Behavior", last_name="Student", birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )
        self.enrollment = Enrollment.objects.create(
            student=student, academic_year=year, section=section, enrollment_date=date(2026, 1, 1),
        )
        self.note = BehaviorNote.objects.create(
            enrollment=self.enrollment, note_type=BehaviorNote.Type.POSITIVE,
            title="Good", description="Description", occurred_on=date(2026, 2, 1), created_by=self.admin,
        )

    def user(self, name, role):
        return User.objects.create_user(username=name, password="StrongPass!123", role=role, must_change_password=False)

    def grant(self, user, code):
        app, codename = code.split(".")
        user.user_permissions.add(Permission.objects.get(content_type__app_label=app, codename=codename))

    def test_actions_are_independent_and_teacher_has_no_invented_scope(self):
        url = "/api/v1/behavior/notes/"
        detail = f"{url}{self.note.pk}/"
        self.client.force_authenticate(self.teacher, token={"client": "web"})
        self.assertEqual(self.client.get(url).status_code, 403)
        self.grant(self.teacher, "behavior.view_behaviornote")
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(detail).status_code, 200)
        payload = {
            "enrollment": str(self.enrollment.pk), "note_type": "positive", "title": "New",
            "description": "Description", "occurred_on": "2026-02-02",
        }
        self.assertEqual(self.client.post(url, payload).status_code, 403)
        self.grant(self.teacher, "behavior.add_behaviornote")
        self.assertEqual(self.client.post(url, payload).status_code, 201)
        self.assertEqual(self.client.patch(detail, {"title": "Changed"}).status_code, 403)
        self.grant(self.teacher, "behavior.change_behaviornote")
        self.assertEqual(self.client.patch(detail, {"title": "Changed"}).status_code, 200)
        self.assertEqual(self.client.delete(detail).status_code, 403)
        self.grant(self.teacher, "behavior.delete_behaviornote")
        self.assertEqual(self.client.delete(detail).status_code, 200)

    def test_role_ceiling_removed_admin_revocation_and_superuser(self):
        url = "/api/v1/behavior/notes/"
        tech = self.user("behavior-tech", User.Role.TECH_SUPPORT)
        self.client.force_authenticate(tech, token={"client": "web"})
        self.assertEqual(self.client.get(url).status_code, 403)
        self.grant(tech, "behavior.view_behaviornote")
        self.assertEqual(self.client.get(f"{url}{self.note.pk}/").status_code, 200)
        self.client.force_authenticate(tech, token={"client": "mobile"})
        self.assertEqual(self.client.get(url).status_code, 403)
        guardian = self.user("behavior-guardian", User.Role.GUARDIAN)
        self.grant(guardian, "behavior.view_behaviornote")
        self.client.force_authenticate(guardian, token={"client": "web"})
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_authenticate(self.admin, token={"client": "web"})
        self.assertEqual(self.client.get(url).status_code, 403)
        root = User.objects.create_superuser(username="behavior-root", password="StrongPass!123")
        self.client.force_authenticate(root, token={"client": "web"})
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.put(f"{url}{self.note.pk}/", {}).status_code, 405)
