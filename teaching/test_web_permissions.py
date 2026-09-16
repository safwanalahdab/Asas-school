from datetime import date

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, GradeSubject, Section, Subject
from accounts.models import User

from .models import TeacherAssignment


class TeachingBusinessPermissionTests(TestCase):
    def setUp(self):
        year = AcademicYear.objects.create(
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
        )
        grade = GradeLevel.objects.create(stage="primary", name="الأول")
        section = Section.objects.create(academic_year=year, grade_level=grade, name="أ")
        subject = Subject.objects.create(name="الرياضيات")
        plan = GradeSubject.objects.create(
            academic_year=year, grade_level=grade, subject=subject
        )
        self.admin = self.make_user("teaching-auth-admin", User.Role.SCHOOL_ADMIN)
        self.teacher = self.make_user("teaching-auth-teacher", User.Role.TEACHER)
        self.other_teacher = self.make_user("teaching-auth-other", User.Role.TEACHER)
        self.tech = self.make_user("teaching-auth-tech", User.Role.TECH_SUPPORT)
        self.root = User.objects.create_superuser(
            username="teaching-auth-root", password="x", must_change_password=False
        )
        for user in (self.admin, self.teacher, self.other_teacher, self.tech):
            user.user_permissions.clear()
        self.assignment = TeacherAssignment.objects.create(
            teacher=self.teacher, grade_subject=plan, section=section,
            start_date=date(2026, 1, 1),
        )
        self.other_assignment = TeacherAssignment.objects.create(
            teacher=self.other_teacher, grade_subject=plan, section=section,
            start_date=date(2026, 1, 1),
        )

    def make_user(self, username, role):
        return User.objects.create_user(
            username=username, password="x", role=role, must_change_password=False
        )

    def grant(self, user, code):
        app_label, codename = code.split(".", 1)
        user.user_permissions.add(Permission.objects.get(
            content_type__app_label=app_label, codename=codename
        ))

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user, token={"client": "web"})
        return client

    def test_school_admin_without_permission_is_forbidden(self):
        self.assertEqual(
            self.client_for(self.admin).get("/api/v1/teaching/assignments/").status_code,
            403,
        )

    def test_view_add_change_delete_are_independent(self):
        client = self.client_for(self.admin)
        base = "/api/v1/teaching/assignments/"
        expectations = (
            ("teaching.view_teacherassignment", lambda: client.get(base), 200),
            ("teaching.add_teacherassignment", lambda: client.post(base, {}, format="json"), 400),
            ("teaching.change_teacherassignment", lambda: client.patch(f"{base}{self.assignment.id}/", {}, format="json"), 400),
            ("teaching.delete_teacherassignment", lambda: client.delete(f"{base}{self.assignment.id}/"), 200),
        )
        for permission, request, expected in expectations:
            with self.subTest(permission=permission):
                self.admin.user_permissions.clear()
                self.assertEqual(request().status_code, 403)
                self.grant(self.admin, permission)
                self.assertEqual(request().status_code, expected)

    def test_end_and_reopen_use_change_permission(self):
        client = self.client_for(self.admin)
        url = f"/api/v1/teaching/assignments/{self.assignment.id}/end/"
        self.assertEqual(client.post(url, {}, format="json").status_code, 403)
        self.grant(self.admin, "teaching.change_teacherassignment")
        self.assertEqual(client.post(url, {}, format="json").status_code, 400)

    def test_teacher_scope_is_preserved(self):
        self.grant(self.teacher, "teaching.view_teacherassignment")
        response = self.client_for(self.teacher).get("/api/v1/teaching/assignments/")
        payload = response.data["data"]
        rows = payload.get("results", payload) if isinstance(payload, dict) else payload
        self.assertEqual({item["id"] for item in rows}, {str(self.assignment.id)})

    def test_nontraditional_role_and_superuser_are_allowed(self):
        self.grant(self.tech, "teaching.view_teacherassignment")
        self.assertEqual(
            self.client_for(self.tech).get("/api/v1/teaching/assignments/").status_code,
            200,
        )
        self.assertEqual(
            self.client_for(self.root).get("/api/v1/teaching/assignments/").status_code,
            200,
        )
