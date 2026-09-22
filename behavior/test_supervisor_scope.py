from datetime import date

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from academics.models import (
    AcademicYear, GradeLevel, Section, SupervisorScope, SupervisorScopeStage,
)
from students.models import Enrollment, Student
from students.services import transfer_student_between_sections
from .models import BehaviorNote


class BehaviorSupervisorScopeTests(TestCase):
    url = "/api/v1/behavior/notes/"

    def setUp(self):
        self.admin = User.objects.create_user(
            username="behavior-scope-admin", password="x", role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
        )
        self.supervisor = User.objects.create_user(
            username="behavior-scope-supervisor", password="x", role=User.Role.SUPERVISOR,
            must_change_password=False,
        )
        self.grant(self.supervisor, "view_behaviornote", "add_behaviornote",
                   "change_behaviornote", "delete_behaviornote")
        self.client = APIClient()
        self.client.force_authenticate(self.supervisor, token={"client": "web"})

        self.old_year = AcademicYear.objects.create(
            start_date=date(2025, 1, 1), end_date=date(2025, 12, 31),
        )
        self.current_year = AcademicYear.objects.create(
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        )
        self.primary_grade = GradeLevel.objects.create(stage="primary", name="Behavior primary")
        self.preparatory_grade = GradeLevel.objects.create(stage="preparatory", name="Behavior preparatory")
        self.old_primary = Section.objects.create(
            academic_year=self.old_year, grade_level=self.primary_grade, name="A",
        )
        self.old_primary_b = Section.objects.create(
            academic_year=self.old_year, grade_level=self.primary_grade, name="B",
        )
        self.current_preparatory = Section.objects.create(
            academic_year=self.current_year, grade_level=self.preparatory_grade, name="A",
        )
        self.student = Student.objects.create(
            first_name="Historical", last_name="Student", birth_date=date(2016, 1, 1),
            gender=Student.Gender.MALE,
        )
        self.old_enrollment = Enrollment.objects.create(
            student=self.student, academic_year=self.old_year, section=self.old_primary,
            enrollment_date=date(2025, 1, 1),
        )
        self.current_enrollment = Enrollment.objects.create(
            student=self.student, academic_year=self.current_year,
            section=self.current_preparatory, enrollment_date=date(2026, 1, 1),
        )
        self.old_note = self.note(self.old_enrollment, "Historical note", date(2025, 3, 1))
        self.current_note = self.note(self.current_enrollment, "Current note", date(2026, 3, 1))

    def grant(self, user, *codenames):
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="behavior", codename__in=codenames,
        ))

    def note(self, enrollment, title, occurred_on):
        return BehaviorNote.objects.create(
            enrollment=enrollment, note_type=BehaviorNote.Type.POSITIVE,
            title=title, description="Description", occurred_on=occurred_on,
            created_by=self.admin,
        )

    def scope(self, *stages):
        scope, _ = SupervisorScope.objects.update_or_create(
            supervisor=self.supervisor,
            defaults={"scope_type": "selected_stages" if stages else "all"},
        )
        scope.stages.all().delete()
        for stage in stages:
            SupervisorScopeStage.objects.create(scope=scope, stage=stage)

    def payload(self, enrollment, title="New note"):
        return {
            "enrollment": str(enrollment.pk), "note_type": "positive",
            "title": title, "description": "Description", "occurred_on": "2025-04-01",
        }

    def detail(self, note):
        return f"{self.url}{note.pk}/"

    def ids(self, response):
        self.assertEqual(response.status_code, 200)
        data = response.data["data"]
        rows = data.get("results", data) if isinstance(data, dict) else data
        return {row["id"] for row in rows}

    def test_historical_list_retrieve_and_filter(self):
        self.scope("primary")
        self.assertEqual(self.ids(self.client.get(self.url)), {str(self.old_note.pk)})
        self.assertEqual(self.client.get(self.detail(self.old_note)).status_code, 200)
        self.assertEqual(self.client.get(self.detail(self.current_note)).status_code, 404)
        self.assertEqual(self.ids(self.client.get(self.url, {
            "enrollment": str(self.current_enrollment.pk),
        })), {str(self.old_note.pk)})
        self.scope("preparatory")
        self.assertEqual(self.ids(self.client.get(self.url)), {str(self.current_note.pk)})

    def test_multiple_all_missing_superuser_and_other_role(self):
        self.assertEqual(self.ids(self.client.get(self.url)), set())
        self.scope("primary", "preparatory")
        both = {str(self.old_note.pk), str(self.current_note.pk)}
        self.assertEqual(self.ids(self.client.get(self.url)), both)
        self.scope()
        self.assertEqual(self.ids(self.client.get(self.url)), both)
        root = User.objects.create_superuser(username="behavior-scope-root", password="x")
        self.client.force_authenticate(root, token={"client": "web"})
        self.assertEqual(self.ids(self.client.get(self.url)), both)
        self.grant(self.admin, "view_behaviornote")
        self.client.force_authenticate(self.admin, token={"client": "web"})
        self.assertEqual(self.ids(self.client.get(self.url)), both)

    def test_create_checks_enrollment_before_side_effects(self):
        self.scope("primary")
        self.assertEqual(self.client.post(
            self.url, self.payload(self.old_enrollment), format="json",
        ).status_code, 201)
        count = BehaviorNote.objects.count()
        self.assertEqual(self.client.post(
            self.url, self.payload(self.current_enrollment), format="json",
        ).status_code, 403)
        self.assertEqual(BehaviorNote.objects.count(), count)

    def test_patch_checks_original_and_replacement_enrollment(self):
        self.scope("primary")
        self.assertEqual(self.client.patch(
            self.detail(self.old_note), {"title": "Changed"}, format="json",
        ).status_code, 200)
        self.assertEqual(self.client.patch(
            self.detail(self.current_note), {"enrollment": str(self.old_enrollment.pk)}, format="json",
        ).status_code, 404)
        self.assertEqual(self.client.patch(
            self.detail(self.old_note), {"enrollment": str(self.current_enrollment.pk)}, format="json",
        ).status_code, 403)
        self.old_note.refresh_from_db()
        self.current_note.refresh_from_db()
        self.assertEqual(self.old_note.enrollment_id, self.old_enrollment.pk)
        self.assertEqual(self.current_note.enrollment_id, self.current_enrollment.pk)
        self.assertEqual(self.old_note.title, "Changed")

    def test_patch_can_move_to_another_enrollment_in_scope(self):
        self.scope("primary")
        second_student = Student.objects.create(
            first_name="Second", last_name="Student", birth_date=date(2016, 2, 1),
            gender=Student.Gender.MALE,
        )
        second = Enrollment.objects.create(
            student=second_student, academic_year=self.old_year, section=self.old_primary,
            enrollment_date=date(2025, 1, 1),
        )
        self.assertEqual(self.client.patch(
            self.detail(self.old_note), {"enrollment": str(second.pk)}, format="json",
        ).status_code, 200)
        self.old_note.refresh_from_db()
        self.assertEqual(self.old_note.enrollment_id, second.pk)

    def test_delete_and_business_permission(self):
        self.scope("primary")
        self.assertEqual(self.client.delete(self.detail(self.current_note)).status_code, 404)
        self.assertTrue(BehaviorNote.objects.filter(pk=self.current_note.pk).exists())
        self.assertEqual(self.client.delete(self.detail(self.old_note)).status_code, 200)
        self.assertFalse(BehaviorNote.objects.filter(pk=self.old_note.pk).exists())
        self.supervisor.user_permissions.clear()
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(
            self.url, self.payload(self.old_enrollment), format="json",
        ).status_code, 403)

    def test_transfer_within_grade_keeps_historical_stage(self):
        self.scope("primary")
        transfer_student_between_sections(
            enrollment=self.old_enrollment, target_section=self.old_primary_b,
            actor=self.admin,
        )
        self.old_enrollment.refresh_from_db()
        self.assertEqual(self.old_enrollment.section_id, self.old_primary_b.pk)
        self.assertEqual(self.client.get(self.detail(self.old_note)).status_code, 200)
        self.assertEqual(self.client.get(self.detail(self.current_note)).status_code, 404)
