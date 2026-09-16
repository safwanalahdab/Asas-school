from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, GradeSubject, Section, Subject, Term
from accounts.models import User
from teaching.models import TeacherAssignment

from .services import create_assessment


class GradesBusinessPermissionTests(TestCase):
    def setUp(self):
        self.year = AcademicYear.objects.create(
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
        )
        self.term = Term.objects.create(
            academic_year=self.year, number=1,
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        )
        self.grade = GradeLevel.objects.create(stage="primary", name="الأول")
        self.assigned = Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name="أ"
        )
        self.unassigned = Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name="ب"
        )
        subject = Subject.objects.create(name="الرياضيات")
        self.plan = GradeSubject.objects.create(
            academic_year=self.year, grade_level=self.grade, subject=subject
        )
        self.admin = self.make_user("grades-auth-admin", User.Role.SCHOOL_ADMIN)
        self.teacher = self.make_user("grades-auth-teacher", User.Role.TEACHER)
        self.tech_support = self.make_user("grades-auth-tech", User.Role.TECH_SUPPORT)
        self.superuser = User.objects.create_superuser(
            username="grades-auth-root", password="x", must_change_password=False
        )
        TeacherAssignment.objects.create(
            teacher=self.teacher, grade_subject=self.plan, section=self.assigned,
            start_date=date(2026, 1, 1),
        )
        self.in_scope = self.make_assessment(self.assigned, "ضمن النطاق")
        self.out_of_scope = self.make_assessment(self.unassigned, "خارج النطاق")

    def make_user(self, username, role):
        return User.objects.create_user(
            username=username, password="x", role=role, must_change_password=False
        )

    def make_assessment(self, section, title):
        return create_assessment(
            section=section, grade_subject=self.plan, term=self.term, title=title,
            max_score=Decimal("20"), assessment_date=date(2026, 9, 1), actor=self.admin,
        )

    def grant(self, user, *codes):
        user.user_permissions.add(*[
            Permission.objects.get(
                content_type__app_label=code.split(".", 1)[0],
                codename=code.split(".", 1)[1],
            )
            for code in codes
        ])

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user, token={"client": "web"})
        return client

    def test_assessment_crud_permissions_are_independent(self):
        self.admin.user_permissions.clear()
        client = self.client_for(self.admin)
        self.grant(self.admin, "grades.view_assessment")
        self.assertEqual(client.get("/api/v1/grades/assessments/").status_code, 200)
        self.assertEqual(
            client.patch(
                f"/api/v1/grades/assessments/{self.in_scope.id}/",
                {"title": "ممنوع"}, format="json",
            ).status_code,
            403,
        )
        self.assertEqual(
            client.delete(f"/api/v1/grades/assessments/{self.in_scope.id}/").status_code,
            403,
        )

    def test_add_assessment_permission_is_independent(self):
        self.admin.user_permissions.clear()
        client = self.client_for(self.admin)
        self.assertEqual(
            client.post("/api/v1/grades/assessments/", {}, format="json").status_code,
            403,
        )
        self.grant(self.admin, "grades.add_assessment")
        self.assertEqual(
            client.post("/api/v1/grades/assessments/", {}, format="json").status_code,
            400,
        )

    def test_teacher_view_and_change_stay_inside_assignment_scope(self):
        self.grant(self.teacher, "grades.view_assessment", "grades.change_assessment")
        client = self.client_for(self.teacher)
        response = client.get("/api/v1/grades/assessments/")
        self.assertEqual(response.status_code, 200)
        payload = response.data["data"]
        rows = payload.get("results", payload) if isinstance(payload, dict) else payload
        ids = {item["id"] for item in rows}
        self.assertEqual(ids, {str(self.in_scope.id)})
        self.assertEqual(
            client.patch(
                f"/api/v1/grades/assessments/{self.out_of_scope.id}/",
                {"title": "ممنوع"}, format="json",
            ).status_code,
            404,
        )

    def test_score_permissions_are_independent(self):
        self.admin.user_permissions.clear()
        client = self.client_for(self.admin)
        self.grant(self.admin, "grades.view_studentscore")
        self.assertEqual(
            client.get(
                f"/api/v1/grades/assessments/{self.in_scope.id}/scores/",
                {"section": str(self.assigned.id)},
            ).status_code,
            200,
        )
        self.assertEqual(
            client.post(
                f"/api/v1/grades/assessments/{self.in_scope.id}/scores/bulk/",
                {"section": str(self.assigned.id), "records": []}, format="json",
            ).status_code,
            403,
        )

    def test_publish_and_grade_wide_permissions_are_independent(self):
        self.admin.user_permissions.clear()
        client = self.client_for(self.admin)
        self.grant(self.admin, "grades.publish_grades")
        self.assertEqual(
            client.post(
                "/api/v1/grades/assessments/publish-section/",
                {"section": str(self.assigned.id), "term": str(self.term.id)},
                format="json",
            ).status_code,
            200,
        )
        self.assertEqual(
            client.post(
                "/api/v1/grades/assessments/create-for-grade/",
                {
                    "grade_subject": str(self.plan.id), "term": str(self.term.id),
                    "title": "ممنوع", "max_score": "20",
                    "assessment_date": "2026-09-02",
                }, format="json",
            ).status_code,
            403,
        )

    def test_nontraditional_role_with_permission_and_superuser_bypass(self):
        self.grant(self.tech_support, "grades.view_assessment")
        self.assertEqual(
            self.client_for(self.tech_support).get("/api/v1/grades/assessments/").status_code,
            200,
        )
        self.assertEqual(
            self.client_for(self.superuser).get("/api/v1/grades/assessments/").status_code,
            200,
        )
