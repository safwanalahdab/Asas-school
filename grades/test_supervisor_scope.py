from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from academics.models import (
    AcademicYear, GradeLevel, GradeSubject, Section, Subject, Term,
    SupervisorScope, SupervisorScopeStage,
)
from students.models import Enrollment, Student
from .models import Assessment, AssessmentSection, StudentScore


class GradesSupervisorScopeTests(TestCase):
    def setUp(self):
        self.year = AcademicYear.objects.create(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        self.term = Term.objects.create(academic_year=self.year, number=1, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        self.subject = Subject.objects.create(name="Scope subject")
        self.user = User.objects.create_user(username="grades-scope", password="x", role=User.Role.SUPERVISOR, must_change_password=False)
        self.grades = {}
        for stage in ("primary", "preparatory"):
            grade = GradeLevel.objects.create(stage=stage, name=stage)
            section = Section.objects.create(academic_year=self.year, grade_level=grade, name="A")
            plan = GradeSubject.objects.create(academic_year=self.year, grade_level=grade, subject=self.subject)
            assessment = Assessment.objects.create(grade_subject=plan, term=self.term, title=stage, max_score=Decimal("20"), assessment_date=date(2026, 2, 1), created_by=self.user)
            AssessmentSection.objects.create(assessment=assessment, section=section)
            student = Student.objects.create(first_name=stage, last_name="Student", birth_date=date(2018, 1, 1), gender=Student.Gender.MALE)
            enrollment = Enrollment.objects.create(student=student, academic_year=self.year, section=section, enrollment_date=date(2026, 1, 5))
            self.grades[stage] = (grade, section, plan, assessment, enrollment)
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label="grades"))
        self.client = APIClient()
        self.client.force_authenticate(self.user, token={"client": "web"})

    def scope(self, *stages):
        scope, _ = SupervisorScope.objects.update_or_create(
            supervisor=self.user,
            defaults={"scope_type": "all" if not stages else "selected_stages"},
        )
        scope.stages.all().delete()
        for stage in stages:
            SupervisorScopeStage.objects.create(scope=scope, stage=stage)

    def test_list_detail_and_missing_scope(self):
        url = "/api/v1/grades/assessments/"
        self.assertEqual(self.client.get(url).data["data"].get("count"), 0)
        self.scope("primary")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["count"], 1)
        outside = self.grades["preparatory"][3]
        self.assertEqual(self.client.get(f"{url}{outside.id}/").status_code, 404)
        self.scope("primary", "preparatory")
        self.assertEqual(self.client.get(url).data["data"]["count"], 2)
        self.scope()
        self.assertEqual(self.client.get(url).data["data"]["count"], 2)

    def test_create_bulk_publish_and_historical_results_reject_outside_scope(self):
        self.scope("primary")
        grade, section, plan, assessment, enrollment = self.grades["preparatory"]
        base = "/api/v1/grades/assessments/"
        payload = {"section": str(section.id), "grade_subject": str(plan.id), "term": str(self.term.id), "title": "New", "max_score": "20", "assessment_date": "2026-02-02"}
        self.assertEqual(self.client.post(base, payload, format="json").status_code, 403)
        self.assertEqual(self.client.post(base + "create-for-grade/", {k: v for k, v in payload.items() if k != "section"}, format="json").status_code, 403)
        self.assertEqual(self.client.post(base + "publish-section/", {"section": str(section.id), "term": str(self.term.id)}, format="json").status_code, 403)
        self.assertEqual(self.client.post(base + "publish-grade/", {"grade_level": str(grade.id), "term": str(self.term.id)}, format="json").status_code, 403)
        self.assertEqual(self.client.get(base + "student-results/", {"enrollment": str(enrollment.id), "term": str(self.term.id)}).status_code, 403)
        inside = self.grades["primary"][3]
        inside_section = self.grades["primary"][1]
        self.assertEqual(self.client.post(f"{base}{inside.id}/scores/bulk/", {"section": str(inside_section.id), "records": [{"enrollment": str(enrollment.id), "score": "10"}]}, format="json").status_code, 403)
        self.assertFalse(StudentScore.objects.exists())
        self.assertEqual(AssessmentSection.objects.filter(status="published").count(), 0)

    def test_detail_mutations_sheet_and_business_permission(self):
        self.scope("primary")
        base = "/api/v1/grades/assessments/"
        outside = self.grades["preparatory"][3]
        inside = self.grades["primary"][3]
        outside_url = f"{base}{outside.id}/"
        self.assertEqual(self.client.patch(outside_url, {"title": "Changed"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(outside_url).status_code, 404)
        self.assertEqual(self.client.get(outside_url + "scores/").status_code, 404)
        self.assertEqual(self.client.get(f"{base}{inside.id}/scores/").status_code, 200)
        outside.refresh_from_db()
        self.assertEqual(outside.title, "preparatory")
        self.user.user_permissions.clear()
        self.assertEqual(self.client.get(base).status_code, 403)

    def test_historical_enrollment_uses_own_stage(self):
        self.scope("primary")
        historical = self.grades["primary"][4]
        self.assertEqual(self.client.get(
            "/api/v1/grades/assessments/student-results/",
            {"enrollment": str(historical.id), "term": str(self.term.id)},
        ).status_code, 200)
        historical.section = self.grades["preparatory"][1]
        historical.save(update_fields=["section"])
        self.assertEqual(self.client.get(
            "/api/v1/grades/assessments/student-results/",
            {"enrollment": str(historical.id), "term": str(self.term.id)},
        ).status_code, 403)

    def test_inconsistent_legacy_assessment_fails_closed(self):
        self.scope("primary")
        assessment = self.grades["primary"][3]
        AssessmentSection.objects.filter(assessment=assessment).update(
            section=self.grades["preparatory"][1]
        )
        base = "/api/v1/grades/assessments/"
        self.assertEqual(self.client.get(base).data["data"]["count"], 0)
        self.assertEqual(self.client.get(f"{base}{assessment.id}/").status_code, 404)
