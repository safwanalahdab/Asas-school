from datetime import date, time
from unittest.mock import patch
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.exceptions import PermissionDenied, ValidationError
from accounts.models import User
from academics.models import AcademicYear, GradeLevel, GradeSubject, Section, Subject
from students.models import Enrollment, Student
from teaching.models import TeacherAssignment
from .domain import normalize_and_validate_record
from .models import AttendanceRecord, AttendanceSheet
from .services import bulk_update_attendance, create_attendance_sheet, update_attendance_record


class AttendanceFixture(TestCase):
    def setUp(self):
        self.today = date(2026, 8, 16)
        self.year = AcademicYear.objects.create(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        self.grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="الأول")
        self.section = Section.objects.create(academic_year=self.year, grade_level=self.grade, name="أ")
        self.other_section = Section.objects.create(academic_year=self.year, grade_level=self.grade, name="ب")
        self.student = Student.objects.create(first_name="أحمد", last_name="علي", birth_date=date(2018, 1, 1), gender=Student.Gender.MALE)
        self.enrollment = Enrollment.objects.create(student=self.student, academic_year=self.year, section=self.section, enrollment_date=date(2026, 1, 1))
        self.teacher = User.objects.create_user(username="teacher", password="x", role=User.Role.TEACHER)
        self.supervisor = User.objects.create_user(username="supervisor", password="x", role=User.Role.SUPERVISOR)
        subject = Subject.objects.create(name="رياضيات")
        plan = GradeSubject.objects.create(academic_year=self.year, grade_level=self.grade, subject=subject)
        TeacherAssignment.objects.create(teacher=self.teacher, grade_subject=plan, section=self.section, start_date=date(2026, 1, 1))

    def payload(self, **changes):
        data = {"enrollment": self.enrollment, "status": AttendanceRecord.Status.PRESENT}
        data.update(changes); return [data]


class ConstraintTests(AttendanceFixture):
    def test_sheet_unique_per_section_date(self):
        AttendanceSheet.objects.create(section=self.section, attendance_date=self.today, created_by=self.supervisor)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttendanceSheet.objects.create(section=self.section, attendance_date=self.today, created_by=self.supervisor)

    def test_record_unique_per_sheet_enrollment(self):
        sheet = AttendanceSheet.objects.create(section=self.section, attendance_date=self.today, created_by=self.supervisor)
        AttendanceRecord.objects.create(sheet=sheet, enrollment=self.enrollment, status="present")
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttendanceRecord.objects.create(sheet=sheet, enrollment=self.enrollment, status="present")


class CreateTests(AttendanceFixture):
    @patch("attendance.services.timezone.localdate", return_value=date(2026, 8, 16))
    def test_assigned_teacher_and_supervisor_can_create(self, mocked):
        sheet = create_attendance_sheet(section=self.section, actor=self.teacher, records=self.payload())
        self.assertEqual(sheet.records.count(), 1)

    @patch("attendance.services.timezone.localdate", return_value=date(2026, 8, 16))
    def test_unassigned_teacher_denied(self, mocked):
        with self.assertRaises(PermissionDenied):
            create_attendance_sheet(section=self.other_section, actor=self.teacher, records=self.payload())

    @patch("attendance.services.timezone.localdate", return_value=date(2026, 8, 14))
    def test_friday_rejected(self, mocked):
        with self.assertRaises(ValidationError): create_attendance_sheet(section=self.section, actor=self.supervisor, records=self.payload())

    @patch("attendance.services.timezone.localdate", return_value=date(2026, 8, 15))
    def test_saturday_rejected(self, mocked):
        with self.assertRaises(ValidationError): create_attendance_sheet(section=self.section, actor=self.supervisor, records=self.payload())

    @patch("attendance.services.timezone.localdate", return_value=date(2026, 8, 16))
    def test_empty_missing_duplicate_and_wrong_roster_rejected(self, mocked):
        for records in ([], self.payload() * 2):
            with self.assertRaises(ValidationError): create_attendance_sheet(section=self.section, actor=self.supervisor, records=records)
        wrong_student = Student.objects.create(first_name="س", last_name="ص", birth_date=date(2018, 1, 1), gender="male")
        wrong = Enrollment.objects.create(student=wrong_student, academic_year=self.year, section=self.other_section, enrollment_date=date(2026, 1, 1))
        with self.assertRaises(ValidationError): create_attendance_sheet(section=self.section, actor=self.supervisor, records=[{"enrollment": wrong, "status": "present"}])

    @patch("attendance.services.timezone.localdate", return_value=date(2026, 8, 16))
    def test_inactive_student_excluded(self, mocked):
        self.student.is_active = False; self.student.save()
        with self.assertRaises(ValidationError): create_attendance_sheet(section=self.section, actor=self.supervisor, records=self.payload())


class RuleAndBulkTests(AttendanceFixture):
    def test_record_rules(self):
        invalid = [
            {"status": "present", "absence_type": "excused"},
            {"status": "absent"},
            {"status": "absent", "absence_type": "excused"},
            {"status": "absent", "absence_type": "unexcused", "arrival_time": time(8)},
            {"status": "present", "arrival_time": time(10), "departure_time": time(9)},
        ]
        for item in invalid:
            with self.assertRaises(ValidationError): normalize_and_validate_record(item)

    def test_unmarked_cleans_old_data(self):
        sheet = AttendanceSheet.objects.create(section=self.section, attendance_date=self.today, created_by=self.supervisor)
        record = AttendanceRecord.objects.create(sheet=sheet, enrollment=self.enrollment, status="present", arrival_time=time(8), arrival_method="school_bus")
        record = update_attendance_record(record=record, data={"status": "unmarked"})
        self.assertIsNone(record.arrival_time); self.assertEqual(record.arrival_method, "")

    def test_bulk_rolls_back_when_one_record_invalid(self):
        second = Student.objects.create(first_name="رامي", last_name="حسن", birth_date=date(2018, 1, 1), gender="male")
        enrollment2 = Enrollment.objects.create(student=second, academic_year=self.year, section=self.section, enrollment_date=date(2026, 1, 1))
        sheet = AttendanceSheet.objects.create(section=self.section, attendance_date=self.today, created_by=self.supervisor)
        one = AttendanceRecord.objects.create(sheet=sheet, enrollment=self.enrollment, status="present")
        two = AttendanceRecord.objects.create(sheet=sheet, enrollment=enrollment2, status="present")
        with self.assertRaises(ValidationError): bulk_update_attendance(sheet=sheet, items=[{"id": one.pk, "notes": "changed"}, {"id": two.pk, "status": "absent"}])
        one.refresh_from_db(); self.assertEqual(one.notes, "")
