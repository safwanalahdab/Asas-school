from datetime import date

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from academics.models import (
    AcademicYear, GradeLevel, GradeSubject, Section, Subject,
    SupervisorScope, SupervisorScopeStage,
)
from teaching.models import TeacherAssignment
from .models import Homework


class HomeworkSupervisorScopeTests(TestCase):
    url = "/api/v1/homework/homeworks/"

    def setUp(self):
        self.admin = User.objects.create_user(
            username="homework-scope-admin", password="x", role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
        )
        self.teacher = User.objects.create_user(
            username="homework-scope-teacher", password="x", role=User.Role.TEACHER,
            must_change_password=False,
        )
        self.supervisor = User.objects.create_user(
            username="homework-scope-supervisor", password="x", role=User.Role.SUPERVISOR,
            must_change_password=False,
        )
        self.grant(self.supervisor, "view_homework", "add_homework",
                   "change_homework", "delete_homework")
        self.client = APIClient()
        self.client.force_authenticate(self.supervisor, token={"client": "web"})
        self.year = AcademicYear.objects.create(
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        )
        subject = Subject.objects.create(name="Scope subject")
        self.assignments = {}
        self.homeworks = {}
        for stage in ("primary", "preparatory"):
            grade = GradeLevel.objects.create(stage=stage, name=f"Homework {stage}")
            section = Section.objects.create(academic_year=self.year, grade_level=grade, name="A")
            plan = GradeSubject.objects.create(
                academic_year=self.year, grade_level=grade, subject=subject,
            )
            assignment = TeacherAssignment.objects.create(
                teacher=self.teacher, grade_subject=plan, section=section,
                start_date=date(2026, 1, 1),
            )
            self.assignments[stage] = assignment
            self.homeworks[stage] = Homework.objects.create(
                teacher_assignment=assignment, title=f"{stage} homework",
                description="Description", homework_date=date(2026, 2, 1),
                due_date=date(2026, 2, 2), created_by=self.admin,
            )

    def grant(self, user, *codenames):
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="homework", codename__in=codenames,
        ))

    def scope(self, *stages):
        scope, _ = SupervisorScope.objects.update_or_create(
            supervisor=self.supervisor,
            defaults={"scope_type": "selected_stages" if stages else "all"},
        )
        scope.stages.all().delete()
        for stage in stages:
            SupervisorScopeStage.objects.create(scope=scope, stage=stage)

    def payload(self, assignment, title="New homework"):
        return {
            "teacher_assignment": str(assignment.pk), "title": title,
            "description": "Description", "homework_date": "2026-02-03",
            "due_date": "2026-02-04",
        }

    def detail(self, homework):
        return f"{self.url}{homework.pk}/"

    def ids(self, response):
        self.assertEqual(response.status_code, 200)
        data = response.data["data"]
        rows = data.get("results", data) if isinstance(data, dict) else data
        return {row["id"] for row in rows}

    def test_list_retrieve_and_filters_follow_assignment_stage(self):
        self.scope("primary")
        primary = self.homeworks["primary"]
        preparatory = self.homeworks["preparatory"]
        self.assertEqual(self.ids(self.client.get(self.url)), {str(primary.pk)})
        self.assertEqual(self.client.get(self.detail(primary)).status_code, 200)
        self.assertEqual(self.client.get(self.detail(preparatory)).status_code, 404)
        self.assertNotIn(str(preparatory.pk), self.ids(self.client.get(
            self.url, {"teacher_assignment": str(self.assignments["preparatory"].pk),
                       "search": "preparatory"},
        )))
        self.scope("preparatory")
        self.assertEqual(self.ids(self.client.get(self.url)), {str(preparatory.pk)})

    def test_multiple_all_missing_superuser_and_admin(self):
        both = {str(item.pk) for item in self.homeworks.values()}
        self.assertEqual(self.ids(self.client.get(self.url)), set())
        self.scope("primary", "preparatory")
        self.assertEqual(self.ids(self.client.get(self.url)), both)
        self.scope()
        self.assertEqual(self.ids(self.client.get(self.url)), both)
        root = User.objects.create_superuser(username="homework-scope-root", password="x")
        self.client.force_authenticate(root, token={"client": "web"})
        self.assertEqual(self.ids(self.client.get(self.url)), both)
        self.grant(self.admin, "view_homework")
        self.client.force_authenticate(self.admin, token={"client": "web"})
        self.assertEqual(self.ids(self.client.get(self.url)), both)

    def test_create_rejects_outside_and_inconsistent_assignment(self):
        self.scope("primary")
        primary = self.assignments["primary"]
        preparatory = self.assignments["preparatory"]
        self.assertEqual(self.client.post(self.url, self.payload(primary), format="json").status_code, 201)
        count = Homework.objects.count()
        self.assertEqual(self.client.post(self.url, self.payload(preparatory), format="json").status_code, 403)
        inconsistent = TeacherAssignment.objects.create(
            teacher=self.teacher, grade_subject=preparatory.grade_subject,
            section=primary.section, start_date=date(2026, 1, 1),
        )
        self.assertEqual(self.client.post(self.url, self.payload(inconsistent), format="json").status_code, 403)
        self.assertEqual(Homework.objects.count(), count)

    def test_patch_checks_original_and_replacement_assignment(self):
        self.scope("primary")
        primary = self.homeworks["primary"]
        preparatory = self.homeworks["preparatory"]
        self.assertEqual(self.client.patch(self.detail(primary), {"title": "Changed"}, format="json").status_code, 200)
        self.assertEqual(self.client.patch(
            self.detail(preparatory), {"teacher_assignment": str(self.assignments["primary"].pk)},
            format="json",
        ).status_code, 404)
        self.assertEqual(self.client.patch(
            self.detail(primary), {"teacher_assignment": str(self.assignments["preparatory"].pk)},
            format="json",
        ).status_code, 403)
        primary.refresh_from_db()
        preparatory.refresh_from_db()
        self.assertEqual(primary.teacher_assignment_id, self.assignments["primary"].pk)
        self.assertEqual(preparatory.teacher_assignment_id, self.assignments["preparatory"].pk)
        self.assertEqual(primary.title, "Changed")

    def test_patch_can_change_to_another_assignment_in_scope(self):
        self.scope("primary")
        original = self.homeworks["primary"]
        assignment = self.assignments["primary"]
        other = TeacherAssignment.objects.create(
            teacher=self.teacher, grade_subject=assignment.grade_subject,
            section=assignment.section, start_date=date(2026, 1, 2),
        )
        self.assertEqual(self.client.patch(
            self.detail(original), {"teacher_assignment": str(other.pk)}, format="json",
        ).status_code, 200)
        original.refresh_from_db()
        self.assertEqual(original.teacher_assignment_id, other.pk)

    def test_delete_business_permission_and_teacher_ownership(self):
        self.scope("primary")
        self.assertEqual(self.client.delete(self.detail(self.homeworks["preparatory"])).status_code, 404)
        self.assertTrue(Homework.objects.filter(pk=self.homeworks["preparatory"].pk).exists())
        self.assertEqual(self.client.delete(self.detail(self.homeworks["primary"])).status_code, 200)
        self.supervisor.user_permissions.clear()
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(
            self.url, self.payload(self.assignments["primary"]), format="json",
        ).status_code, 403)
        self.grant(self.teacher, "view_homework", "add_homework")
        self.client.force_authenticate(self.teacher, token={"client": "web"})
        self.assertEqual(self.ids(self.client.get(self.url)), {str(self.homeworks["preparatory"].pk)})
        self.assertEqual(self.client.post(
            self.url, self.payload(self.assignments["primary"]), format="json",
        ).status_code, 201)

    def test_inconsistent_legacy_homework_is_hidden_from_supervisor(self):
        self.scope("primary")
        assignment = TeacherAssignment.objects.create(
            teacher=self.teacher,
            grade_subject=self.assignments["preparatory"].grade_subject,
            section=self.assignments["primary"].section,
            start_date=date(2026, 1, 1),
        )
        homework = Homework.objects.create(
            teacher_assignment=assignment, title="Inconsistent",
            description="Description", homework_date=date(2026, 2, 1),
            due_date=date(2026, 2, 2), created_by=self.admin,
        )
        self.assertNotIn(str(homework.pk), self.ids(self.client.get(self.url)))
        self.assertEqual(self.client.get(self.detail(homework)).status_code, 404)

    def test_teacher_assignment_end_date_does_not_change_existing_homework_scope(self):
        self.scope("primary")
        assignment = self.assignments["primary"]
        assignment.end_date = date(2026, 2, 1)
        assignment.save(update_fields=["end_date"])
        self.assertEqual(self.client.get(self.detail(self.homeworks["primary"])).status_code, 200)
