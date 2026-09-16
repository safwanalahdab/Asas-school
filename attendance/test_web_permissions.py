from datetime import date

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, GradeSubject, Section, Subject
from accounts.models import User
from students.models import Enrollment, Student
from teaching.models import TeacherAssignment

from .models import AttendanceRecord, AttendanceSheet


class AttendanceBusinessPermissionTests(TestCase):
    def setUp(self):
        self.year = AcademicYear.objects.create(
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
        )
        self.grade = GradeLevel.objects.create(stage="primary", name="الأول")
        self.assigned = Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name="أ"
        )
        self.unassigned = Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name="ب"
        )
        subject = Subject.objects.create(name="الرياضيات")
        plan = GradeSubject.objects.create(
            academic_year=self.year, grade_level=self.grade, subject=subject
        )
        self.teacher = self.make_user("attendance-teacher", User.Role.TEACHER)
        TeacherAssignment.objects.create(
            teacher=self.teacher,
            grade_subject=plan,
            section=self.assigned,
            start_date=date(2026, 1, 1),
        )
        self.tech_support = self.make_user("attendance-tech", User.Role.TECH_SUPPORT)
        self.admin = self.make_user("attendance-admin", User.Role.SCHOOL_ADMIN)
        self.superuser = User.objects.create_superuser(
            username="attendance-root", password="x", must_change_password=False
        )
        self.assigned_sheet, self.assigned_record = self.make_sheet(self.assigned)
        self.unassigned_sheet, self.unassigned_record = self.make_sheet(self.unassigned)

    def make_user(self, username, role):
        return User.objects.create_user(
            username=username, password="x", role=role, must_change_password=False
        )

    def make_sheet(self, section):
        student = Student.objects.create(
            first_name=section.name, last_name="طالب", birth_date=date(2018, 1, 1), gender="male"
        )
        enrollment = Enrollment.objects.create(
            student=student,
            academic_year=self.year,
            section=section,
            enrollment_date=date(2026, 1, 1),
        )
        sheet = AttendanceSheet.objects.create(
            section=section, attendance_date=date(2026, 9, 15), created_by=self.admin
        )
        record = AttendanceRecord.objects.create(
            sheet=sheet, enrollment=enrollment, status="present"
        )
        return sheet, record

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

    def test_missing_view_permission_denies_school_admin(self):
        self.admin.user_permissions.clear()
        response = self.client_for(self.admin).get("/api/v1/attendance/sheets/")
        self.assertEqual(response.status_code, 403)

    def test_teacher_view_is_limited_to_assigned_sections(self):
        self.grant(self.teacher, "attendance.view_attendancesheet")
        response = self.client_for(self.teacher).get("/api/v1/attendance/sheets/")
        self.assertEqual(response.status_code, 200)
        payload = response.data["data"]
        rows = payload.get("results", payload) if isinstance(payload, dict) else payload
        ids = {item["id"] for item in rows}
        self.assertEqual(ids, {str(self.assigned_sheet.id)})
        self.assertEqual(
            self.client_for(self.teacher).get(
                f"/api/v1/attendance/sheets/{self.unassigned_sheet.id}/"
            ).status_code,
            404,
        )

    def test_teacher_changes_records_only_inside_assignment_scope(self):
        self.grant(self.teacher, "attendance.change_attendancerecord")
        client = self.client_for(self.teacher)
        self.assertEqual(
            client.patch(
                f"/api/v1/attendance/records/{self.assigned_record.id}/",
                {"notes": "ok"}, format="json",
            ).status_code,
            200,
        )
        self.assertEqual(
            client.patch(
                f"/api/v1/attendance/records/{self.unassigned_record.id}/",
                {"notes": "blocked"}, format="json",
            ).status_code,
            404,
        )

    def test_sheet_and_record_change_permissions_are_independent(self):
        self.admin.user_permissions.clear()
        self.grant(self.admin, "attendance.change_attendancerecord")
        client = self.client_for(self.admin)
        self.assertEqual(
            client.post(
                f"/api/v1/attendance/sheets/{self.assigned_sheet.id}/bulk-update/",
                {"records": [{"id": str(self.assigned_record.id), "notes": "bulk"}]},
                format="json",
            ).status_code,
            200,
        )
        self.assertEqual(
            client.post(
                f"/api/v1/attendance/sheets/{self.assigned_sheet.id}/normal-departure/",
                {"departure_time": "13:00", "departure_method": "guardian"},
                format="json",
            ).status_code,
            403,
        )

    def test_add_sheet_permission_is_independent(self):
        self.admin.user_permissions.clear()
        client = self.client_for(self.admin)
        self.assertEqual(
            client.post("/api/v1/attendance/sheets/", {}, format="json").status_code,
            403,
        )
        self.grant(self.admin, "attendance.add_attendancesheet")
        self.assertEqual(
            client.post("/api/v1/attendance/sheets/", {}, format="json").status_code,
            400,
        )

    def test_nontraditional_role_with_permission_and_superuser_bypass(self):
        self.grant(self.tech_support, "attendance.view_attendancesheet")
        self.assertEqual(
            self.client_for(self.tech_support).get("/api/v1/attendance/sheets/").status_code,
            200,
        )
        self.assertEqual(
            self.client_for(self.superuser).get("/api/v1/attendance/sheets/").status_code,
            200,
        )
