from datetime import date, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from academics.models import AcademicYear, GradeLevel, Section
from students.models import Enrollment, GuardianStudent, Student

from .models import AttendanceRecord, AttendanceSheet


User = get_user_model()


class MobileAttendanceTests(TestCase):
    today = date(2026, 8, 30)

    def setUp(self):
        self.client = APIClient()
        self.guardian = self.make_user("attendance-guardian", User.Role.GUARDIAN)
        self.other_guardian = self.make_user("attendance-other", User.Role.GUARDIAN)
        self.staff = self.make_user("attendance-staff", User.Role.SCHOOL_ADMIN)
        self.year = AcademicYear.objects.create(
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
            status=AcademicYear.Status.ACTIVE,
        )
        self.old_year = AcademicYear.objects.create(
            start_date=date(2025, 1, 1), end_date=date(2025, 12, 31),
            status=AcademicYear.Status.CLOSED,
        )
        self.grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY, name="Grade Mobile Attendance",
        )
        self.section = Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name="A",
        )
        self.old_section = Section.objects.create(
            academic_year=self.old_year, grade_level=self.grade, name="Old",
        )
        self.child = self.make_child("Owned", self.guardian)
        self.other_child = self.make_child("Other", self.other_guardian)
        self.enrollment = Enrollment.objects.create(
            student=self.child, academic_year=self.year, section=self.section,
            enrollment_date=date(2026, 1, 1),
        )
        self.old_enrollment = Enrollment.objects.create(
            student=self.child, academic_year=self.old_year, section=self.old_section,
            enrollment_date=date(2025, 1, 1),
        )

    def make_user(self, username, role):
        return User.objects.create_user(
            username=username, password="StrongPass!493", role=role,
            must_change_password=False,
        )

    def make_child(self, first_name, guardian):
        student = Student.objects.create(
            first_name=first_name, last_name="Child",
            birth_date=date(2015, 1, 1), gender=Student.Gender.MALE,
        )
        GuardianStudent.objects.create(guardian=guardian, student=student)
        return student

    def history_url(self, child=None):
        return f"/api/v1/mobile/children/{(child or self.child).id}/attendance/"

    def today_url(self, child=None):
        return f"{self.history_url(child)}today/"

    def authenticate(self, client="mobile"):
        token = RefreshToken.for_user(self.guardian)
        token["client"] = client
        token["token_version"] = self.guardian.token_version
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    def make_record(self, status, target_date=None, enrollment=None, section=None, **kwargs):
        sheet = AttendanceSheet.objects.create(
            section=section or self.section,
            attendance_date=target_date or self.today,
            created_by=self.staff,
        )
        return AttendanceRecord.objects.create(
            sheet=sheet, enrollment=enrollment or self.enrollment,
            status=status, **kwargs,
        )

    def get_today(self, child=None):
        with patch("attendance.mobile_views.timezone.localdate", return_value=self.today):
            return self.client.get(self.today_url(child))

    def test_today_present_contract_and_private_fields(self):
        self.make_record(
            AttendanceRecord.Status.PRESENT, arrival_time=time(7, 45),
            arrival_method=Enrollment.TransportationMethod.SCHOOL_BUS,
            departure_time=time(13, 30),
            departure_method=Enrollment.TransportationMethod.GUARDIAN,
            notes="private",
        )
        self.authenticate()
        response = self.get_today()
        data = response.data["data"]
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["is_recorded"])
        self.assertEqual(data["status"], "present")
        self.assertEqual(data["date"], "2026-08-30")
        self.assertNotIn("notes", data["record"])
        self.assertNotIn("created_by", data["record"])
        self.assertNotIn("sheet", data["record"])
        self.assertNotIn("enrollment", data["record"])

    def test_today_absent_includes_absence_data(self):
        self.make_record(
            AttendanceRecord.Status.ABSENT,
            absence_type=AttendanceRecord.AbsenceType.EXCUSED,
            absence_reason="Illness",
            absence_reason_source=AttendanceRecord.AbsenceReasonSource.GUARDIAN,
        )
        self.authenticate()
        record = self.get_today().data["data"]["record"]
        self.assertEqual(record["status"], "absent")
        self.assertEqual(record["absence_type"], "excused")
        self.assertEqual(record["absence_reason_source"], "guardian")

    def test_today_unmarked_missing_and_old_are_not_recorded(self):
        self.authenticate()
        response = self.get_today()
        self.assertFalse(response.data["data"]["is_recorded"])
        self.assertIsNone(response.data["data"]["status"])
        old = self.make_record(AttendanceRecord.Status.PRESENT, self.today - timedelta(days=1))
        self.assertIsNone(self.get_today().data["data"]["record"])
        old.delete()
        old.sheet.delete()
        self.make_record(AttendanceRecord.Status.UNMARKED)
        self.assertIsNone(self.get_today().data["data"]["record"])

    def test_today_no_enrollment_is_successful_not_recorded(self):
        child = self.make_child("NoEnrollment", self.guardian)
        self.authenticate()
        response = self.get_today(child)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["data"]["academic_year"])
        self.assertFalse(response.data["data"]["is_recorded"])
        self.assertIsNone(response.data["data"]["record"])

    def test_history_records_summary_order_and_excludes_unmarked_and_old_year(self):
        present = self.make_record(AttendanceRecord.Status.PRESENT, date(2026, 8, 28))
        absent = self.make_record(
            AttendanceRecord.Status.ABSENT, date(2026, 8, 29),
            absence_type=AttendanceRecord.AbsenceType.EXCUSED,
            absence_reason="Illness",
            absence_reason_source=AttendanceRecord.AbsenceReasonSource.GUARDIAN,
        )
        self.make_record(AttendanceRecord.Status.UNMARKED, date(2026, 8, 27))
        self.make_record(
            AttendanceRecord.Status.ABSENT, date(2025, 8, 29),
            enrollment=self.old_enrollment, section=self.old_section,
            absence_type=AttendanceRecord.AbsenceType.UNEXCUSED,
        )
        self.authenticate()
        data = self.client.get(self.history_url()).data["data"]
        self.assertEqual([item["id"] for item in data["records"]], [str(absent.id), str(present.id)])
        self.assertEqual(data["summary"], {
            "total_recorded_days": 2, "present_count": 1, "absent_count": 1,
            "excused_absence_count": 1, "unexcused_absence_count": 0,
            "attendance_rate_percentage": "50.00",
        })

    def test_history_date_filters_affect_summary(self):
        self.make_record(AttendanceRecord.Status.PRESENT, date(2026, 8, 1))
        self.make_record(
            AttendanceRecord.Status.ABSENT, date(2026, 8, 20),
            absence_type=AttendanceRecord.AbsenceType.UNEXCUSED,
        )
        self.authenticate()
        response = self.client.get(self.history_url(), {
            "date_from": "2026-08-10", "date_to": "2026-08-30",
        })
        self.assertEqual(response.data["data"]["summary"]["total_recorded_days"], 1)
        self.assertEqual(response.data["data"]["summary"]["attendance_rate_percentage"], "0.00")

    def test_history_status_filters_records_but_not_summary(self):
        self.make_record(AttendanceRecord.Status.PRESENT, date(2026, 8, 1))
        absent = self.make_record(
            AttendanceRecord.Status.ABSENT, date(2026, 8, 2),
            absence_type=AttendanceRecord.AbsenceType.UNEXCUSED,
        )
        self.authenticate()
        data = self.client.get(self.history_url(), {"status": "absent"}).data["data"]
        self.assertEqual([item["id"] for item in data["records"]], [str(absent.id)])
        self.assertEqual(data["summary"]["total_recorded_days"], 2)
        self.assertEqual(data["summary"]["present_count"], 1)

    def test_history_validates_dates_and_status(self):
        self.authenticate()
        self.assertEqual(self.client.get(self.history_url(), {
            "date_from": "2026-09-02", "date_to": "2026-09-01",
        }).status_code, 400)
        self.assertEqual(self.client.get(self.history_url(), {"status": "unmarked"}).status_code, 400)
        self.assertEqual(self.client.get(self.history_url(), {"date_from": "bad"}).status_code, 400)

    def test_history_pagination_defaults_to_20_and_caps_at_50(self):
        for offset in range(25):
            self.make_record(AttendanceRecord.Status.PRESENT, self.today - timedelta(days=offset))
        self.authenticate()
        first = self.client.get(self.history_url()).data["data"]
        self.assertEqual(len(first["records"]), 20)
        self.assertEqual(first["pagination"], {
            "page": 1, "page_size": 20, "total_pages": 2, "total_items": 25,
        })
        capped = self.client.get(self.history_url(), {"page_size": 500}).data["data"]
        self.assertEqual(capped["pagination"]["page_size"], 50)
        self.assertEqual(len(capped["records"]), 25)

    def test_history_no_enrollment_has_zero_contract(self):
        child = self.make_child("NoHistory", self.guardian)
        self.authenticate()
        data = self.client.get(self.history_url(child)).data["data"]
        self.assertIsNone(data["academic_year"])
        self.assertEqual(data["records"], [])
        self.assertEqual(data["summary"]["total_recorded_days"], 0)
        self.assertEqual(data["summary"]["attendance_rate_percentage"], "0.00")

    def test_current_enrollment_history_survives_section_transfer(self):
        record = self.make_record(AttendanceRecord.Status.PRESENT, date(2026, 8, 1))
        new_section = Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name="B",
        )
        self.enrollment.section = new_section
        self.enrollment.save(update_fields=["section"])
        self.authenticate()
        ids = [item["id"] for item in self.client.get(self.history_url()).data["data"]["records"]]
        self.assertIn(str(record.id), ids)

    def test_security_and_read_only_boundaries(self):
        self.authenticate()
        for url in (self.today_url(self.other_child), self.history_url(self.other_child)):
            self.assertEqual(self.client.get(url).status_code, 404)
        for url in (self.today_url(), self.history_url()):
            for method in ("post", "put", "patch", "delete"):
                self.assertEqual(getattr(self.client, method)(url, {}).status_code, 405)
        self.client.credentials()
        self.assertEqual(self.client.get(self.history_url()).status_code, 401)
        self.authenticate(client="web")
        self.assertEqual(self.client.get(self.history_url()).status_code, 401)
        self.guardian.must_change_password = True
        self.guardian.save(update_fields=["must_change_password"])
        self.authenticate()
        self.assertEqual(self.client.get(self.history_url()).status_code, 403)
