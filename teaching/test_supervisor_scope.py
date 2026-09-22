from datetime import date

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from academics.models import (
    AcademicYear, GradeLevel, GradeSubject, Section, Subject,
    SupervisorScope, SupervisorScopeStage,
)
from audit_logs.models import AuditLog
from .models import TeacherAssignment


class TeachingSupervisorScopeTests(TestCase):
    url = "/api/v1/teaching/assignments/"

    def setUp(self):
        self.year = AcademicYear.objects.create(
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        )
        self.subject = Subject.objects.create(name="Scope subject")
        self.teacher = User.objects.create_user(
            username="scope-teacher", password="x", role=User.Role.TEACHER,
            must_change_password=False,
        )
        self.supervisor = User.objects.create_user(
            username="scope-supervisor", password="x", role=User.Role.SUPERVISOR,
            must_change_password=False,
        )
        self.admin = User.objects.create_user(
            username="scope-admin", password="x", role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
        )
        self.grant(self.supervisor, "view_teacherassignment", "add_teacherassignment",
                   "change_teacherassignment", "delete_teacherassignment")
        self.client = APIClient()
        self.client.force_authenticate(self.supervisor, token={"client": "web"})
        self.assignments = {}
        for stage in ("primary", "preparatory"):
            grade = GradeLevel.objects.create(stage=stage, name=f"Teaching {stage}")
            section = Section.objects.create(academic_year=self.year, grade_level=grade, name="A")
            plan = GradeSubject.objects.create(
                academic_year=self.year, grade_level=grade, subject=self.subject,
            )
            self.assignments[stage] = TeacherAssignment.objects.create(
                teacher=self.teacher, section=section, grade_subject=plan,
                start_date=date(2026, 1, 1),
            )
        self.primary_b = Section.objects.create(
            academic_year=self.year,
            grade_level=self.assignments["primary"].section.grade_level,
            name="B",
        )
        self.preparatory_b = Section.objects.create(
            academic_year=self.year,
            grade_level=self.assignments["preparatory"].section.grade_level,
            name="B",
        )

    def grant(self, user, *codenames):
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="teaching", codename__in=codenames,
        ))

    def scope(self, *stages):
        scope, _ = SupervisorScope.objects.update_or_create(
            supervisor=self.supervisor,
            defaults={"scope_type": "selected_stages" if stages else "all"},
        )
        scope.stages.all().delete()
        for stage in stages:
            SupervisorScopeStage.objects.create(scope=scope, stage=stage)

    def payload(self, stage, *, section=None):
        assignment = self.assignments[stage]
        return {
            "teacher": str(self.teacher.pk),
            "grade_subject": str(assignment.grade_subject_id),
            "section": str((section or assignment.section).pk),
            "start_date": "2026-03-01",
        }

    def detail(self, assignment):
        return f"{self.url}{assignment.pk}/"

    def ids(self, response):
        self.assertEqual(response.status_code, 200)
        data = response.data["data"]
        rows = data.get("results", data) if isinstance(data, dict) else data
        return {row["id"] for row in rows}

    def test_list_retrieve_filters_and_teacher_with_two_stages(self):
        self.scope("primary")
        primary = self.assignments["primary"]
        preparatory = self.assignments["preparatory"]
        self.assertEqual(self.ids(self.client.get(self.url)), {str(primary.pk)})
        self.assertEqual(self.client.get(self.detail(primary)).status_code, 200)
        self.assertEqual(self.client.get(self.detail(preparatory)).status_code, 404)
        self.assertEqual(self.ids(self.client.get(
            self.url, {"teacher": str(self.teacher.pk), "search": "preparatory"},
        )), set())
        self.scope("preparatory")
        self.assertEqual(self.ids(self.client.get(self.url)), {str(preparatory.pk)})

    def test_missing_multiple_all_superuser_and_other_roles(self):
        both = {str(item.pk) for item in self.assignments.values()}
        self.assertEqual(self.ids(self.client.get(self.url)), set())
        self.assertEqual(self.client.post(
            self.url, self.payload("primary", section=self.primary_b), format="json",
        ).status_code, 403)
        self.scope("primary", "preparatory")
        self.assertEqual(self.ids(self.client.get(self.url)), both)
        self.scope()
        self.assertEqual(self.ids(self.client.get(self.url)), both)
        root = User.objects.create_superuser(username="scope-root", password="x")
        self.client.force_authenticate(root, token={"client": "web"})
        self.assertEqual(self.ids(self.client.get(self.url)), both)
        self.grant(self.admin, "view_teacherassignment")
        self.client.force_authenticate(self.admin, token={"client": "web"})
        self.assertEqual(self.ids(self.client.get(self.url)), both)
        self.grant(self.teacher, "view_teacherassignment")
        self.client.force_authenticate(self.teacher, token={"client": "web"})
        self.assertEqual(self.ids(self.client.get(self.url)), both)

    def test_create_checks_final_section_and_subject_before_audit(self):
        self.scope("primary")
        count = TeacherAssignment.objects.count()
        audits = AuditLog.objects.count()
        outside = self.payload("preparatory", section=self.preparatory_b)
        self.assertEqual(self.client.post(self.url, outside, format="json").status_code, 403)
        self.assertEqual(TeacherAssignment.objects.count(), count)
        self.assertEqual(AuditLog.objects.count(), audits)
        inconsistent = self.payload("preparatory", section=self.primary_b)
        self.assertEqual(self.client.post(self.url, inconsistent, format="json").status_code, 400)
        self.assertEqual(TeacherAssignment.objects.count(), count)
        inside = self.payload("primary", section=self.primary_b)
        self.assertEqual(self.client.post(self.url, inside, format="json").status_code, 201)
        self.assertEqual(TeacherAssignment.objects.count(), count + 1)

    def test_patch_checks_original_and_final_pair(self):
        self.scope("primary")
        primary = self.assignments["primary"]
        preparatory = self.assignments["preparatory"]
        original_primary_section_id = primary.section_id
        original_preparatory_section_id = preparatory.section_id
        audits = AuditLog.objects.count()
        self.assertEqual(self.client.patch(
            self.detail(preparatory), {"section": str(self.primary_b.pk)}, format="json",
        ).status_code, 404)
        self.assertEqual(self.client.patch(
            self.detail(primary), {
                "section": str(self.preparatory_b.pk),
                "grade_subject": str(preparatory.grade_subject_id),
            }, format="json",
        ).status_code, 403)
        primary.refresh_from_db()
        preparatory.refresh_from_db()
        self.assertEqual(primary.section_id, original_primary_section_id)
        self.assertEqual(preparatory.section_id, original_preparatory_section_id)
        self.assertEqual(AuditLog.objects.count(), audits)
        self.assertEqual(self.client.patch(
            self.detail(primary), {"section": str(self.primary_b.pk)}, format="json",
        ).status_code, 200)
        primary.refresh_from_db()
        self.assertEqual(primary.section_id, self.primary_b.pk)

    def test_end_reopen_and_delete_require_scoped_uuid(self):
        self.scope("primary")
        primary = self.assignments["primary"]
        preparatory = self.assignments["preparatory"]
        audits = AuditLog.objects.count()
        self.assertEqual(self.client.post(
            self.detail(preparatory) + "end/", {"end_date": "2026-04-01"}, format="json",
        ).status_code, 404)
        preparatory.end_date = date(2026, 4, 1)
        preparatory.save(update_fields=["end_date"])
        self.assertEqual(self.client.post(
            self.detail(preparatory) + "reopen/", {}, format="json",
        ).status_code, 404)
        self.assertEqual(self.client.delete(self.detail(preparatory)).status_code, 404)
        self.assertEqual(AuditLog.objects.count(), audits)
        preparatory.refresh_from_db()
        self.assertEqual(preparatory.end_date, date(2026, 4, 1))
        self.assertEqual(self.client.post(
            self.detail(primary) + "end/", {"end_date": "2026-04-01"}, format="json",
        ).status_code, 200)
        self.assertEqual(self.client.post(
            self.detail(primary) + "reopen/", {}, format="json",
        ).status_code, 200)
        self.assertEqual(self.client.delete(self.detail(primary)).status_code, 200)
        self.assertFalse(TeacherAssignment.objects.filter(pk=primary.pk).exists())

    def test_historical_and_inconsistent_assignment(self):
        self.scope("primary")
        primary = self.assignments["primary"]
        primary.end_date = date(2026, 2, 1)
        primary.save(update_fields=["end_date"])
        self.assertEqual(self.client.get(self.detail(primary)).status_code, 200)
        inconsistent = TeacherAssignment.objects.create(
            teacher=self.teacher, section=self.primary_b,
            grade_subject=self.assignments["preparatory"].grade_subject,
            start_date=date(2026, 1, 1),
        )
        self.assertNotIn(str(inconsistent.pk), self.ids(self.client.get(self.url)))
        self.assertEqual(self.client.get(self.detail(inconsistent)).status_code, 404)
        self.assertEqual(self.client.delete(self.detail(inconsistent)).status_code, 404)

    def test_business_permission_is_still_required(self):
        self.scope("primary")
        self.supervisor.user_permissions.clear()
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(
            self.url, self.payload("primary", section=self.primary_b), format="json",
        ).status_code, 403)
