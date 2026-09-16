from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User

from .views import (
    AcademicYearViewSet, GradeLevelViewSet, GradeSubjectViewSet,
    SectionViewSet, SubjectViewSet, TermViewSet,
)


class AcademicsBusinessPermissionTests(TestCase):
    resources = (
        ("academic-years", "academicyear", AcademicYearViewSet),
        ("terms", "term", TermViewSet),
        ("grade-levels", "gradelevel", GradeLevelViewSet),
        ("sections", "section", SectionViewSet),
        ("subjects", "subject", SubjectViewSet),
        ("grade-subjects", "gradesubject", GradeSubjectViewSet),
    )

    def setUp(self):
        self.admin = self.make_user("academics-auth-admin", User.Role.SCHOOL_ADMIN)
        self.teacher = self.make_user("academics-auth-teacher", User.Role.TEACHER)
        self.tech = self.make_user("academics-auth-tech", User.Role.TECH_SUPPORT)
        self.root = User.objects.create_superuser(
            username="academics-auth-root", password="x", must_change_password=False
        )
        for user in (self.admin, self.teacher, self.tech):
            user.user_permissions.clear()

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

    def test_every_resource_exposes_standard_business_permission_mapping(self):
        for _route, model_name, viewset in self.resources:
            with self.subTest(model=model_name):
                self.assertEqual(viewset.action_permissions, {
                    "list": f"academics.view_{model_name}",
                    "retrieve": f"academics.view_{model_name}",
                    "create": f"academics.add_{model_name}",
                    "partial_update": f"academics.change_{model_name}",
                    "destroy": f"academics.delete_{model_name}",
                })

    def test_view_add_change_delete_are_independent_for_every_resource(self):
        client = self.client_for(self.admin)
        missing = "00000000-0000-0000-0000-000000000000"
        for route, model_name, _viewset in self.resources:
            base = f"/api/v1/academics/{route}/"
            operations = (
                (f"academics.view_{model_name}", lambda: client.get(base), 200),
                (f"academics.add_{model_name}", lambda: client.post(base, {}, format="json"), 400),
                (f"academics.change_{model_name}", lambda: client.patch(f"{base}{missing}/", {}, format="json"), 404),
                (f"academics.delete_{model_name}", lambda: client.delete(f"{base}{missing}/"), 404),
            )
            for permission, request, expected in operations:
                with self.subTest(route=route, permission=permission):
                    self.admin.user_permissions.clear()
                    self.assertEqual(request().status_code, 403)
                    self.grant(self.admin, permission)
                    self.assertEqual(request().status_code, expected)

    def test_role_is_not_a_ceiling_and_school_admin_needs_permission(self):
        url = "/api/v1/academics/subjects/"
        self.assertEqual(self.client_for(self.admin).get(url).status_code, 403)
        for user in (self.teacher, self.tech):
            with self.subTest(role=user.role):
                self.grant(user, "academics.view_subject")
                self.assertEqual(self.client_for(user).get(url).status_code, 200)

    def test_superuser_bypass(self):
        self.assertEqual(
            self.client_for(self.root).get("/api/v1/academics/subjects/").status_code,
            200,
        )
