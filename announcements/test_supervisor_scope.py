from datetime import timedelta

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from academics.models import AcademicYear, GradeLevel, Section, SupervisorScope, SupervisorScopeStage
from notifications.models import Notification
from .models import Announcement


class AnnouncementSupervisorScopeTests(TestCase):
    url = "/api/v1/announcements/"

    def setUp(self):
        self.today = timezone.localdate()
        self.admin = User.objects.create_user(
            username="announcement-scope-admin", password="x", role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
        )
        self.supervisor = User.objects.create_user(
            username="announcement-scope-supervisor", password="x", role=User.Role.SUPERVISOR,
            must_change_password=False,
        )
        self.grant(self.supervisor, "view_announcement", "add_announcement",
                   "change_announcement", "delete_announcement")
        self.client = APIClient()
        self.client.force_authenticate(self.supervisor, token={"client": "web"})
        self.year = AcademicYear.objects.create(
            start_date=self.today - timedelta(days=100),
            end_date=self.today + timedelta(days=100),
        )
        self.grades = {}
        self.sections = {}
        for stage in ("primary", "preparatory"):
            grade = GradeLevel.objects.create(stage=stage, name=f"Announcement {stage}")
            section = Section.objects.create(academic_year=self.year, grade_level=grade, name="A")
            self.grades[stage] = grade
            self.sections[stage] = section
        self.global_note = self.note("all", "Global")
        self.primary_grade_note = self.note("grades", "Primary grade", grades=[self.grades["primary"]])
        self.preparatory_grade_note = self.note("grades", "Preparatory grade", grades=[self.grades["preparatory"]])
        self.primary_section_note = self.note("sections", "Primary section", sections=[self.sections["primary"]])
        self.preparatory_section_note = self.note("sections", "Preparatory section", sections=[self.sections["preparatory"]])
        self.mixed_grade_note = self.note("grades", "Mixed grade", grades=list(self.grades.values()))
        self.mixed_section_note = self.note("sections", "Mixed section", sections=list(self.sections.values()))

    def grant(self, user, *codenames):
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="announcements", codename__in=codenames,
        ))

    def scope(self, *stages):
        scope, _ = SupervisorScope.objects.update_or_create(
            supervisor=self.supervisor,
            defaults={"scope_type": "selected_stages" if stages else "all"},
        )
        scope.stages.all().delete()
        for stage in stages:
            SupervisorScopeStage.objects.create(scope=scope, stage=stage)

    def note(self, scope, title, *, grades=(), sections=()):
        note = Announcement.objects.create(
            scope=scope, title=title, content="Content", publish_date=self.today,
            created_by=self.admin,
        )
        note.grade_levels.set(grades)
        note.sections.set(sections)
        return note

    def payload(self, scope="all", *, grades=(), sections=(), title="Created"):
        return {
            "scope": scope, "title": title, "content": "Content",
            "publish_date": str(self.today),
            "grade_levels": [str(item.pk) for item in grades],
            "sections": [str(item.pk) for item in sections],
        }

    def detail(self, note):
        return f"{self.url}{note.pk}/"

    def ids(self, response):
        self.assertEqual(response.status_code, 200)
        data = response.data["data"]
        rows = data.get("results", data) if isinstance(data, dict) else data
        return {row["id"] for row in rows}

    def test_selected_stage_list_retrieve_and_filters_require_all_targets(self):
        self.scope("primary")
        expected = {str(item.pk) for item in (
            self.global_note, self.primary_grade_note, self.primary_section_note,
        )}
        self.assertEqual(self.ids(self.client.get(self.url)), expected)
        for note in (self.preparatory_grade_note, self.preparatory_section_note,
                     self.mixed_grade_note, self.mixed_section_note):
            self.assertEqual(self.client.get(self.detail(note)).status_code, 404)
        self.assertEqual(self.ids(self.client.get(
            self.url, {"grade_level": str(self.grades["preparatory"].pk)},
        )), set())
        self.assertEqual(self.ids(self.client.get(
            self.url, {"section": str(self.sections["preparatory"].pk),
                       "search": "Mixed"},
        )), set())

    def test_multiple_all_missing_superuser_and_other_role(self):
        all_ids = {str(note.pk) for note in Announcement.objects.all()}
        self.assertEqual(self.ids(self.client.get(self.url)), set())
        self.assertEqual(self.client.get(self.detail(self.global_note)).status_code, 404)
        self.scope("primary", "preparatory")
        self.assertEqual(self.ids(self.client.get(self.url)), all_ids)
        self.scope()
        self.assertEqual(self.ids(self.client.get(self.url)), all_ids)
        root = User.objects.create_superuser(username="announcement-scope-root", password="x")
        self.client.force_authenticate(root, token={"client": "web"})
        self.assertEqual(self.ids(self.client.get(self.url)), all_ids)
        self.grant(self.admin, "view_announcement")
        self.client.force_authenticate(self.admin, token={"client": "web"})
        self.assertEqual(self.ids(self.client.get(self.url)), all_ids)

    def test_create_global_and_targeted(self):
        self.scope("primary")
        self.assertEqual(self.client.post(self.url, self.payload(), format="json").status_code, 201)
        self.assertEqual(self.client.post(self.url, self.payload(
            "grades", grades=[self.grades["primary"]], title="Inside grade",
        ), format="json").status_code, 201)
        self.assertEqual(self.client.post(self.url, self.payload(
            "sections", sections=[self.sections["primary"]], title="Inside section",
        ), format="json").status_code, 201)
        count = Announcement.objects.count()
        notifications = Notification.objects.count()
        for data in (
            self.payload("grades", grades=[self.grades["preparatory"]]),
            self.payload("grades", grades=list(self.grades.values())),
            self.payload("sections", sections=[self.sections["preparatory"]]),
            self.payload("sections", sections=list(self.sections.values())),
        ):
            self.assertEqual(self.client.post(self.url, data, format="json").status_code, 403)
        self.assertEqual(Announcement.objects.count(), count)
        self.assertEqual(Notification.objects.count(), notifications)

    def test_patch_original_and_final_targets(self):
        self.scope("primary")
        self.assertEqual(self.client.patch(
            self.detail(self.global_note), {"title": "Changed global"}, format="json",
        ).status_code, 200)
        self.assertEqual(self.client.patch(
            self.detail(self.primary_grade_note), {"title": "Changed primary"}, format="json",
        ).status_code, 200)
        self.assertEqual(self.client.patch(
            self.detail(self.preparatory_grade_note),
            {"grade_levels": [str(self.grades["primary"].pk)]}, format="json",
        ).status_code, 404)
        self.assertEqual(self.client.patch(
            self.detail(self.primary_grade_note),
            {"grade_levels": [str(grade.pk) for grade in self.grades.values()]},
            format="json",
        ).status_code, 403)
        self.assertEqual(self.client.patch(
            self.detail(self.primary_section_note),
            {"sections": [str(section.pk) for section in self.sections.values()]},
            format="json",
        ).status_code, 403)
        self.assertEqual(self.client.patch(
            self.detail(self.global_note),
            {"scope": "grades", "grade_levels": [str(self.grades["preparatory"].pk)]},
            format="json",
        ).status_code, 403)
        self.global_note.refresh_from_db()
        self.assertEqual(self.global_note.scope, "all")
        self.primary_grade_note.refresh_from_db()
        self.assertEqual(list(self.primary_grade_note.grade_levels.all()), [self.grades["primary"]])
        self.assertEqual(self.primary_grade_note.title, "Changed primary")
        self.assertEqual(self.client.patch(
            self.detail(self.primary_grade_note),
            {"scope": "all", "grade_levels": []}, format="json",
        ).status_code, 200)
        self.primary_grade_note.refresh_from_db()
        self.assertEqual(self.primary_grade_note.scope, "all")

    def test_delete_global_and_in_scope_but_not_mixed(self):
        self.scope("primary")
        self.assertEqual(self.client.delete(self.detail(self.mixed_section_note)).status_code, 404)
        self.assertTrue(Announcement.objects.filter(pk=self.mixed_section_note.pk).exists())
        self.assertEqual(self.client.delete(self.detail(self.global_note)).status_code, 200)
        self.assertEqual(self.client.delete(self.detail(self.primary_section_note)).status_code, 200)
        self.assertFalse(Announcement.objects.filter(pk=self.global_note.pk).exists())

    def test_missing_scope_and_business_permissions_cover_global(self):
        self.assertEqual(self.client.post(self.url, self.payload(), format="json").status_code, 403)
        self.assertEqual(self.client.patch(self.detail(self.global_note), {"title": "No"}).status_code, 404)
        self.assertEqual(self.client.delete(self.detail(self.global_note)).status_code, 404)
        self.scope("primary")
        self.supervisor.user_permissions.clear()
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, self.payload(), format="json").status_code, 403)
        self.assertEqual(self.client.patch(self.detail(self.global_note), {"title": "No"}).status_code, 403)
        self.assertEqual(self.client.delete(self.detail(self.global_note)).status_code, 403)
