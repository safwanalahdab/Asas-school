from datetime import date

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from academics.models import AcademicYear, GradeLevel, Section, SupervisorScope, SupervisorScopeStage
from notifications.models import Notification
from students.models import Enrollment, GuardianStudent, Student
from .models import SchoolRequest


class SchoolRequestSupervisorScopeTests(TestCase):
    url = "/api/v1/requests/"

    def setUp(self):
        self.guardian = User.objects.create_user(
            username="request-scope-guardian", password="x", role=User.Role.GUARDIAN,
            must_change_password=False,
        )
        self.admin = User.objects.create_user(
            username="request-scope-admin", password="x", role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
        )
        self.secretariat = User.objects.create_user(
            username="request-scope-secretariat", password="x", role=User.Role.SECRETARIAT,
            must_change_password=False,
        )
        self.supervisor = User.objects.create_user(
            username="request-scope-supervisor", password="x", role=User.Role.SUPERVISOR,
            must_change_password=False,
        )
        for user in (self.supervisor, self.admin, self.secretariat):
            self.grant(user, "view_schoolrequest", "reply_to_request")
        self.client = APIClient()
        self.client.force_authenticate(self.supervisor, token={"client": "web"})
        self.old_year = AcademicYear.objects.create(
            start_date=date(2025, 1, 1), end_date=date(2025, 12, 31),
        )
        self.active_year = AcademicYear.objects.create(
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
            status=AcademicYear.Status.ACTIVE,
        )
        self.primary_grade = GradeLevel.objects.create(stage="primary", name="Request primary")
        self.preparatory_grade = GradeLevel.objects.create(stage="preparatory", name="Request preparatory")
        self.old_primary_section = Section.objects.create(
            academic_year=self.old_year, grade_level=self.primary_grade, name="A",
        )
        self.active_primary_section = Section.objects.create(
            academic_year=self.active_year, grade_level=self.primary_grade, name="A",
        )
        self.active_preparatory_section = Section.objects.create(
            academic_year=self.active_year, grade_level=self.preparatory_grade, name="A",
        )
        self.primary_student = self.student("Primary")
        self.preparatory_student = self.student("Preparatory")
        self.old_only_student = self.student("Old only")
        self.unenrolled_student = self.student("Unenrolled")
        Enrollment.objects.create(
            student=self.primary_student, academic_year=self.active_year,
            section=self.active_primary_section, enrollment_date=date(2026, 1, 1),
        )
        Enrollment.objects.create(
            student=self.preparatory_student, academic_year=self.old_year,
            section=self.old_primary_section, enrollment_date=date(2025, 1, 1),
        )
        Enrollment.objects.create(
            student=self.preparatory_student, academic_year=self.active_year,
            section=self.active_preparatory_section, enrollment_date=date(2026, 1, 1),
        )
        Enrollment.objects.create(
            student=self.old_only_student, academic_year=self.old_year,
            section=self.old_primary_section, enrollment_date=date(2025, 1, 1),
        )
        self.requests = {
            "primary": self.school_request(self.primary_student),
            "preparatory": self.school_request(self.preparatory_student),
            "old_only": self.school_request(self.old_only_student),
            "unenrolled": self.school_request(self.unenrolled_student),
            "no_student": self.school_request(None),
        }

    def grant(self, user, *codenames):
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="school_requests", codename__in=codenames,
        ))

    def student(self, name):
        student = Student.objects.create(
            first_name=name, last_name="Student", birth_date=date(2016, 1, 1),
            gender=Student.Gender.MALE,
        )
        GuardianStudent.objects.create(guardian=self.guardian, student=student)
        return student

    def school_request(self, student):
        return SchoolRequest.objects.create(
            request_type=SchoolRequest.RequestType.INQUIRY,
            details="Question", guardian=self.guardian, student=student,
        )

    def scope(self, *stages):
        scope, _ = SupervisorScope.objects.update_or_create(
            supervisor=self.supervisor,
            defaults={"scope_type": "selected_stages" if stages else "all"},
        )
        scope.stages.all().delete()
        for stage in stages:
            SupervisorScopeStage.objects.create(scope=scope, stage=stage)

    def detail(self, item):
        return f"{self.url}{item.pk}/"

    def ids(self, response):
        self.assertEqual(response.status_code, 200)
        data = response.data["data"]
        rows = data.get("results", data) if isinstance(data, dict) else data
        return {row["id"] for row in rows}

    def test_selected_stage_uses_active_enrollment_not_history(self):
        self.scope("primary")
        primary = self.requests["primary"]
        self.assertEqual(self.ids(self.client.get(self.url)), {str(primary.pk)})
        self.assertEqual(self.client.get(self.detail(primary)).status_code, 200)
        for key in ("preparatory", "old_only", "unenrolled", "no_student"):
            self.assertEqual(self.client.get(self.detail(self.requests[key])).status_code, 404)
        self.assertEqual(self.ids(self.client.get(
            self.url, {"student": str(self.preparatory_student.pk)},
        )), set())

    def test_multiple_all_missing_and_no_active_year(self):
        self.assertEqual(self.ids(self.client.get(self.url)), set())
        self.scope("primary", "preparatory")
        expected = {str(self.requests[key].pk) for key in ("primary", "preparatory")}
        self.assertEqual(self.ids(self.client.get(self.url)), expected)
        self.scope()
        self.assertEqual(self.ids(self.client.get(self.url)), {
            str(item.pk) for item in self.requests.values()
        })
        self.scope("primary")
        self.active_year.status = AcademicYear.Status.CLOSED
        self.active_year.save(update_fields=["status"])
        self.assertEqual(self.ids(self.client.get(self.url)), set())

    def test_answer_rejects_external_and_unlinked_before_effects(self):
        self.scope("primary")
        for key in ("preparatory", "old_only", "unenrolled", "no_student"):
            item = self.requests[key]
            count = Notification.objects.count()
            response = self.client.post(
                self.detail(item) + "answer/",
                {"school_response": "Answer"}, format="json",
            )
            self.assertEqual(response.status_code, 404)
            item.refresh_from_db()
            self.assertEqual(item.status, SchoolRequest.Status.NEW)
            self.assertEqual(item.school_response, "")
            self.assertEqual(Notification.objects.count(), count)
        primary = self.requests["primary"]
        self.assertEqual(self.client.post(
            self.detail(primary) + "answer/", {"school_response": "Allowed"},
            format="json",
        ).status_code, 200)
        primary.refresh_from_db()
        self.assertEqual(primary.status, SchoolRequest.Status.ANSWERED)
        self.assertEqual(Notification.objects.count(), 1)

    def test_permissions_and_other_roles_remain_unchanged(self):
        self.scope("primary")
        self.supervisor.user_permissions.clear()
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(
            self.detail(self.requests["primary"]) + "answer/",
            {"school_response": "No"}, format="json",
        ).status_code, 403)
        all_ids = {str(item.pk) for item in self.requests.values()}
        for user in (self.admin, self.secretariat):
            self.client.force_authenticate(user, token={"client": "web"})
            self.assertEqual(self.ids(self.client.get(self.url)), all_ids)
        root = User.objects.create_superuser(username="request-scope-root", password="x")
        self.client.force_authenticate(root, token={"client": "web"})
        self.assertEqual(self.ids(self.client.get(self.url)), all_ids)
        self.client.force_authenticate(self.guardian, token={"client": "web"})
        self.assertEqual(self.ids(self.client.get(self.url)), all_ids)
        self.assertEqual(self.client.post(
            self.url, {"request_type": "suggestion", "details": "New"},
            format="json",
        ).status_code, 201)

    def test_supervisor_cannot_create_patch_or_delete(self):
        self.scope("primary")
        self.assertEqual(self.client.post(
            self.url, {"request_type": "suggestion", "details": "New",
                       "student": str(self.primary_student.pk)}, format="json",
        ).status_code, 403)
        self.assertEqual(self.client.patch(
            self.detail(self.requests["primary"]), {"student": None}, format="json",
        ).status_code, 405)
        self.assertEqual(self.client.delete(self.detail(self.requests["primary"])).status_code, 405)
