from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, GradeSubject, Section, Subject
from teaching.models import TeacherAssignment

from .models import Homework


User = get_user_model()


class HomeworkWebPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.teacher = self.user("homework-teacher", User.Role.TEACHER)
        self.other_teacher = self.user("homework-other", User.Role.TEACHER)
        self.admin = self.user("homework-admin", User.Role.SCHOOL_ADMIN)
        self.teacher.user_permissions.clear()
        self.admin.user_permissions.clear()
        year = AcademicYear.objects.create(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="Homework grade")
        section = Section.objects.create(academic_year=year, grade_level=grade, name="A")
        subject = Subject.objects.create(name="Homework subject")
        grade_subject = GradeSubject.objects.create(academic_year=year, grade_level=grade, subject=subject)
        self.assignment = TeacherAssignment.objects.create(
            teacher=self.teacher, grade_subject=grade_subject, section=section,
            start_date=date(2026, 1, 1),
        )
        self.other_assignment = TeacherAssignment.objects.create(
            teacher=self.other_teacher, grade_subject=grade_subject, section=section,
            start_date=date(2026, 1, 1),
        )
        self.own = self.homework(self.assignment)
        self.other = self.homework(self.other_assignment)

    def user(self, name, role):
        return User.objects.create_user(username=name, password="StrongPass!123", role=role, must_change_password=False)

    def grant(self, user, code):
        app, codename = code.split(".")
        user.user_permissions.add(Permission.objects.get(content_type__app_label=app, codename=codename))

    def homework(self, assignment):
        return Homework.objects.create(
            teacher_assignment=assignment, title="Homework", description="Description",
            homework_date=date(2026, 2, 1), due_date=date(2026, 2, 2), created_by=self.admin,
        )

    def payload(self, assignment):
        return {
            "teacher_assignment": str(assignment.pk), "title": "New homework",
            "description": "Description", "homework_date": "2026-02-03", "due_date": "2026-02-04",
        }

    def test_teacher_permissions_and_assignment_scope(self):
        url = "/api/v1/homework/homeworks/"
        self.client.force_authenticate(self.teacher, token={"client": "web"})
        self.assertEqual(self.client.get(url).status_code, 403)
        self.grant(self.teacher, "homework.view_homework")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["data"]["results"]], [str(self.own.pk)])
        self.assertEqual(self.client.get(f"{url}{self.own.pk}/").status_code, 200)
        self.assertEqual(self.client.get(f"{url}{self.other.pk}/").status_code, 404)
        self.assertEqual(self.client.post(url, self.payload(self.assignment)).status_code, 403)
        self.grant(self.teacher, "homework.add_homework")
        self.assertEqual(self.client.post(url, self.payload(self.assignment)).status_code, 201)
        self.assertEqual(self.client.post(url, self.payload(self.other_assignment)).status_code, 403)
        self.assertEqual(self.client.patch(f"{url}{self.own.pk}/", {"title": "Changed"}).status_code, 403)
        self.grant(self.teacher, "homework.change_homework")
        self.assertEqual(self.client.patch(f"{url}{self.own.pk}/", {"title": "Changed"}).status_code, 200)
        self.assertEqual(self.client.patch(f"{url}{self.other.pk}/", {"title": "Changed"}).status_code, 404)
        self.assertEqual(self.client.delete(f"{url}{self.own.pk}/").status_code, 403)
        self.grant(self.teacher, "homework.delete_homework")
        self.assertEqual(self.client.delete(f"{url}{self.other.pk}/").status_code, 404)
        self.assertEqual(self.client.delete(f"{url}{self.own.pk}/").status_code, 200)

    def test_direct_permission_removes_role_ceiling_and_superuser_bypasses(self):
        url = "/api/v1/homework/homeworks/"
        tech = self.user("homework-tech", User.Role.TECH_SUPPORT)
        self.client.force_authenticate(tech, token={"client": "web"})
        self.assertEqual(self.client.get(url).status_code, 403)
        self.grant(tech, "homework.view_homework")
        self.assertEqual(self.client.get(f"{url}{self.other.pk}/").status_code, 200)
        self.client.force_authenticate(tech, token={"client": "mobile"})
        self.assertEqual(self.client.get(url).status_code, 403)
        guardian = self.user("homework-guardian", User.Role.GUARDIAN)
        self.grant(guardian, "homework.view_homework")
        self.client.force_authenticate(guardian, token={"client": "web"})
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_authenticate(self.admin, token={"client": "web"})
        self.assertEqual(self.client.get(url).status_code, 403)
        root = User.objects.create_superuser(username="homework-root", password="StrongPass!123")
        self.client.force_authenticate(root, token={"client": "web"})
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.put(f"{url}{self.other.pk}/", {}).status_code, 405)
