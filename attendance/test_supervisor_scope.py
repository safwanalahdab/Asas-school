from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from academics.models import (
    AcademicYear,
    GradeLevel,
    Section,
    SupervisorScope,
    SupervisorScopeStage,
)
from students.models import Enrollment, Student

from .models import AttendanceRecord, AttendanceSheet


class AttendanceSupervisorScopeApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.year = AcademicYear.objects.create(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            status=AcademicYear.Status.ACTIVE,
        )
        cls.primary = GradeLevel.objects.create(stage="primary", name="Primary")
        cls.preparatory = GradeLevel.objects.create(
            stage="preparatory", name="Preparatory"
        )
        cls.secondary = GradeLevel.objects.create(stage="secondary", name="Secondary")
        cls.primary_section = cls.make_section(cls.primary, "Primary A")
        cls.primary_create_section = cls.make_section(cls.primary, "Primary B")
        cls.preparatory_section = cls.make_section(cls.preparatory, "Preparatory A")
        cls.secondary_section = cls.make_section(cls.secondary, "Secondary A")

        cls.admin = cls.make_user("attendance-scope-admin", User.Role.SCHOOL_ADMIN)
        cls.all_supervisor = cls.make_user("attendance-scope-all", User.Role.SUPERVISOR)
        SupervisorScope.objects.create(
            supervisor=cls.all_supervisor, scope_type=SupervisorScope.ScopeType.ALL
        )
        cls.primary_supervisor = cls.make_scoped_supervisor(
            "attendance-scope-primary", ["primary"]
        )
        cls.multi_supervisor = cls.make_scoped_supervisor(
            "attendance-scope-multi", ["primary", "preparatory"]
        )
        cls.missing_supervisor = cls.make_user(
            "attendance-scope-missing", User.Role.SUPERVISOR
        )
        cls.root = User.objects.create_superuser(
            username="attendance-scope-root", password="x", must_change_password=False
        )

        permissions = Permission.objects.filter(content_type__app_label="attendance")
        for user in (
            cls.admin,
            cls.all_supervisor,
            cls.primary_supervisor,
            cls.multi_supervisor,
            cls.missing_supervisor,
        ):
            user.user_permissions.add(*permissions)

        cls.primary_enrollment = cls.make_enrollment(cls.primary_section, "Primary")
        cls.primary_create_enrollment = cls.make_enrollment(
            cls.primary_create_section, "Create"
        )
        cls.preparatory_enrollment = cls.make_enrollment(
            cls.preparatory_section, "Preparatory"
        )
        cls.secondary_enrollment = cls.make_enrollment(cls.secondary_section, "Secondary")
        cls.primary_sheet, cls.primary_record = cls.make_sheet(
            cls.primary_section, cls.primary_enrollment, date(2026, 9, 14)
        )
        cls.preparatory_sheet, cls.preparatory_record = cls.make_sheet(
            cls.preparatory_section, cls.preparatory_enrollment, date(2026, 9, 15)
        )
        cls.secondary_sheet, cls.secondary_record = cls.make_sheet(
            cls.secondary_section, cls.secondary_enrollment, date(2026, 9, 16)
        )

    @classmethod
    def make_user(cls, username, role):
        return User.objects.create_user(
            username=username, password="x", role=role, must_change_password=False
        )

    @classmethod
    def make_scoped_supervisor(cls, username, stages):
        user = cls.make_user(username, User.Role.SUPERVISOR)
        scope = SupervisorScope.objects.create(
            supervisor=user, scope_type=SupervisorScope.ScopeType.SELECTED_STAGES
        )
        SupervisorScopeStage.objects.bulk_create(
            [SupervisorScopeStage(scope=scope, stage=stage) for stage in stages]
        )
        return user

    @classmethod
    def make_section(cls, grade_level, name):
        return Section.objects.create(
            academic_year=cls.year, grade_level=grade_level, name=name
        )

    @classmethod
    def make_enrollment(cls, section, first_name):
        student = Student.objects.create(
            first_name=first_name,
            last_name="Student",
            birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )
        return Enrollment.objects.create(
            student=student,
            academic_year=cls.year,
            section=section,
            enrollment_date=date(2026, 1, 1),
        )

    @classmethod
    def make_sheet(cls, section, enrollment, attendance_date):
        sheet = AttendanceSheet.objects.create(
            section=section, attendance_date=attendance_date, created_by=cls.admin
        )
        record = AttendanceRecord.objects.create(
            sheet=sheet, enrollment=enrollment, status=AttendanceRecord.Status.PRESENT
        )
        return sheet, record

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user, token={"client": "web"})
        return client

    @staticmethod
    def ids(response):
        data = response.data["data"]
        rows = data.get("results", data) if isinstance(data, dict) else data
        return {row["id"] for row in rows}

    def test_selected_and_multi_stage_sheet_lists_are_filtered(self):
        url = "/api/v1/attendance/sheets/"
        self.assertEqual(
            self.ids(self.client_for(self.primary_supervisor).get(url)),
            {str(self.primary_sheet.id)},
        )
        self.assertEqual(
            self.ids(self.client_for(self.multi_supervisor).get(url)),
            {str(self.primary_sheet.id), str(self.preparatory_sheet.id)},
        )

    def test_sheet_direct_uuid_and_filters_cannot_bypass_scope(self):
        client = self.client_for(self.primary_supervisor)
        detail = f"/api/v1/attendance/sheets/{self.secondary_sheet.id}/"
        self.assertEqual(client.get(detail).status_code, 404)
        response = client.get(
            "/api/v1/attendance/sheets/", {"section": self.secondary_section.id}
        )
        self.assertEqual(self.ids(response), set())

    def test_all_missing_and_superuser_sheet_access(self):
        url = "/api/v1/attendance/sheets/"
        expected = {
            str(self.primary_sheet.id),
            str(self.preparatory_sheet.id),
            str(self.secondary_sheet.id),
        }
        self.assertEqual(self.ids(self.client_for(self.all_supervisor).get(url)), expected)
        self.assertEqual(self.ids(self.client_for(self.missing_supervisor).get(url)), set())
        self.assertEqual(self.ids(self.client_for(self.root).get(url)), expected)

    @patch("attendance.services.timezone.localdate", return_value=date(2026, 9, 20))
    def test_create_checks_target_section_before_service(self, _localdate):
        client = self.client_for(self.primary_supervisor)
        payload = {
            "section": str(self.primary_create_section.id),
            "records": [
                {"enrollment": str(self.primary_create_enrollment.id), "status": "present"}
            ],
        }
        self.assertEqual(client.post("/api/v1/attendance/sheets/", payload, format="json").status_code, 201)
        blocked = {
            "section": str(self.secondary_section.id),
            "records": [{"enrollment": str(self.secondary_enrollment.id), "status": "present"}],
        }
        self.assertEqual(client.post("/api/v1/attendance/sheets/", blocked, format="json").status_code, 403)
        self.assertFalse(
            AttendanceSheet.objects.filter(
                section=self.secondary_section, attendance_date=date(2026, 9, 20)
            ).exists()
        )

    def test_missing_scope_cannot_create(self):
        payload = {
            "section": str(self.secondary_section.id),
            "records": [{"enrollment": str(self.secondary_enrollment.id), "status": "present"}],
        }
        response = self.client_for(self.missing_supervisor).post(
            "/api/v1/attendance/sheets/", payload, format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_create_rejects_out_of_scope_enrollment_foreign_key(self):
        payload = {
            "section": str(self.primary_create_section.id),
            "records": [
                {"enrollment": str(self.secondary_enrollment.id), "status": "present"}
            ],
        }
        response = self.client_for(self.primary_supervisor).post(
            "/api/v1/attendance/sheets/", payload, format="json"
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            AttendanceSheet.objects.filter(section=self.primary_create_section).exists()
        )

    def test_roster_is_scoped_without_leaking_students(self):
        client = self.client_for(self.primary_supervisor)
        url = "/api/v1/attendance/sheets/roster/"
        allowed = client.get(url, {"section": self.primary_section.id})
        blocked = client.get(url, {"section": self.secondary_section.id})
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(blocked.status_code, 403)
        self.assertNotIn(str(self.secondary_enrollment.id), str(blocked.data))

    def test_bulk_update_and_normal_departure_use_scoped_sheet_object(self):
        client = self.client_for(self.primary_supervisor)
        outside_bulk = client.post(
            f"/api/v1/attendance/sheets/{self.secondary_sheet.id}/bulk-update/",
            {"records": [{"id": str(self.secondary_record.id), "notes": "blocked"}]},
            format="json",
        )
        outside_departure = client.post(
            f"/api/v1/attendance/sheets/{self.secondary_sheet.id}/normal-departure/",
            {"departure_time": "13:00", "departure_method": "guardian"},
            format="json",
        )
        self.assertEqual(outside_bulk.status_code, 404)
        self.assertEqual(outside_departure.status_code, 404)
        self.secondary_record.refresh_from_db()
        self.assertEqual(self.secondary_record.notes, "")
        self.assertIsNone(self.secondary_record.departure_time)

    def test_bulk_update_rejects_record_from_another_sheet(self):
        response = self.client_for(self.primary_supervisor).post(
            f"/api/v1/attendance/sheets/{self.primary_sheet.id}/bulk-update/",
            {"records": [{"id": str(self.secondary_record.id), "notes": "blocked"}]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.secondary_record.refresh_from_db()
        self.assertEqual(self.secondary_record.notes, "")

    def test_record_list_retrieve_and_patch_are_scoped_by_sheet(self):
        client = self.client_for(self.primary_supervisor)
        url = "/api/v1/attendance/records/"
        self.assertEqual(self.ids(client.get(url)), {str(self.primary_record.id)})
        detail = f"{url}{self.secondary_record.id}/"
        self.assertEqual(client.get(detail).status_code, 404)
        self.assertEqual(client.patch(detail, {"notes": "blocked"}, format="json").status_code, 404)
        self.secondary_record.refresh_from_db()
        self.assertEqual(self.secondary_record.notes, "")
        allowed = client.patch(
            f"{url}{self.primary_record.id}/", {"notes": "allowed"}, format="json"
        )
        self.assertEqual(allowed.status_code, 200)

    def test_historical_record_scope_uses_sheet_not_current_enrollment_section(self):
        self.primary_enrollment.section = self.secondary_section
        self.primary_enrollment.save(update_fields=["section", "updated_at"])
        client = self.client_for(self.primary_supervisor)
        self.assertEqual(
            client.get(f"/api/v1/attendance/records/{self.primary_record.id}/").status_code,
            200,
        )
        self.assertEqual(
            client.get(f"/api/v1/attendance/records/{self.secondary_record.id}/").status_code,
            404,
        )

    def test_business_permission_is_still_required(self):
        self.primary_supervisor.user_permissions.remove(
            Permission.objects.get(
                content_type__app_label="attendance", codename="view_attendancesheet"
            )
        )
        self.assertEqual(
            self.client_for(self.primary_supervisor).get("/api/v1/attendance/sheets/").status_code,
            403,
        )

    def test_non_supervisor_direct_permission_behavior_is_unchanged(self):
        tech = self.make_user("attendance-scope-tech", User.Role.TECH_SUPPORT)
        tech.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="attendance", codename="view_attendancesheet"
            )
        )
        self.assertEqual(
            self.ids(self.client_for(tech).get("/api/v1/attendance/sheets/")),
            {
                str(self.primary_sheet.id),
                str(self.preparatory_sheet.id),
                str(self.secondary_sheet.id),
            },
        )
