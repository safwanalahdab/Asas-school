from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, Section
from accounts.models import User
from audit_logs.models import AuditLog
from notifications.models import Notification
from students.models import Enrollment, GuardianStudent, Student, StudentAuditLog

from .domain import normalize_and_validate_record
from .models import AttendanceRecord, AttendanceSheet
from .services import (
    apply_normal_departure, bulk_update_attendance, create_attendance_sheet,
    get_effective_attendance_roster, update_attendance_record,
)


class AttendanceFixture(TestCase):
    def setUp(self):
        self.today = date(2026, 8, 16)
        self.year = AcademicYear.objects.create(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        self.grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="الأول")
        self.section_a = Section.objects.create(academic_year=self.year, grade_level=self.grade, name="أ")
        self.section_b = Section.objects.create(academic_year=self.year, grade_level=self.grade, name="ب")
        self.section_c = Section.objects.create(academic_year=self.year, grade_level=self.grade, name="ج")
        self.student = Student.objects.create(first_name="أحمد", last_name="علي", birth_date=date(2018, 1, 1), gender=Student.Gender.MALE)
        self.enrollment = Enrollment.objects.create(
            student=self.student, academic_year=self.year, section=self.section_a,
            enrollment_date=date(2026, 1, 1),
            usual_arrival_method=Enrollment.TransportationMethod.SCHOOL_BUS,
            usual_departure_method=None,
        )
        self.supervisor = self.make_user("supervisor", User.Role.SUPERVISOR)
        self.school_admin = self.make_user("school-admin", User.Role.SCHOOL_ADMIN)
        self.teacher = self.make_user("teacher", User.Role.TEACHER)
        self.secretariat = self.make_user("secretariat", User.Role.SECRETARIAT)
        self.tech_support = self.make_user("tech-support", User.Role.TECH_SUPPORT)
        self.guardian = self.make_user("guardian", User.Role.GUARDIAN)
        self.superuser = User.objects.create_superuser(username="root", password="x", must_change_password=False)

    def make_user(self, username, role):
        return User.objects.create_user(username=username, password="x", role=role, must_change_password=False)

    def payload(self, enrollment=None, **changes):
        data = {"enrollment": enrollment or self.enrollment, "status": AttendanceRecord.Status.PRESENT}
        data.update(changes)
        return [data]

    def sheet_with_record(self, *, status=AttendanceRecord.Status.PRESENT, **fields):
        sheet, _ = AttendanceSheet.objects.get_or_create(
            section=self.section_a, attendance_date=self.today,
            defaults={"created_by": self.supervisor},
        )
        record, _ = AttendanceRecord.objects.get_or_create(
            sheet=sheet, enrollment=self.enrollment,
            defaults={"status": status, **fields},
        )
        return sheet, record

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user, token={"client": "web"})
        return client

    def log_transfer(self, old_section, new_section, when):
        log = StudentAuditLog.objects.create(
            event_type=StudentAuditLog.EventType.SECTION_TRANSFER, actor=self.supervisor,
            enrollment=self.enrollment, old_section=old_section, new_section=new_section,
        )
        StudentAuditLog.objects.filter(pk=log.pk).update(created_at=when)
        self.enrollment.section = new_section
        self.enrollment.save(update_fields=["section", "updated_at"])

    def local_datetime(self, target_date, hour):
        return timezone.make_aware(datetime.combine(target_date, time(hour)), timezone.get_current_timezone())


class AttendanceNotificationTests(AttendanceFixture):
    def setUp(self):
        super().setUp()
        GuardianStudent.objects.create(guardian=self.guardian, student=self.student)

    @patch("attendance.services.timezone.localdate", return_value=date(2026, 8, 16))
    def test_final_absence_notifies_but_present_does_not(self, _localdate):
        create_attendance_sheet(
            section=self.section_a, actor=self.supervisor,
            records=self.payload(
                status=AttendanceRecord.Status.ABSENT,
                absence_type=AttendanceRecord.AbsenceType.UNEXCUSED,
                absence_reason="private reason",
            ),
        )
        notification = Notification.objects.get()
        record = AttendanceRecord.objects.get()
        self.assertEqual(notification.recipient, self.guardian)
        self.assertEqual(notification.student, self.student)
        self.assertEqual(notification.resource_id, record.id)
        self.assertEqual(notification.event_key, f"attendance:{record.id}:absent")
        self.assertNotIn("private reason", notification.body)

    def test_correction_back_to_absent_does_not_duplicate(self):
        _sheet, record = self.sheet_with_record()
        update_attendance_record(
            record=record,
            data={"status": AttendanceRecord.Status.ABSENT,
                  "absence_type": AttendanceRecord.AbsenceType.UNEXCUSED},
        )
        update_attendance_record(record=record, data={"status": AttendanceRecord.Status.PRESENT})
        update_attendance_record(
            record=record,
            data={"status": AttendanceRecord.Status.ABSENT,
                  "absence_type": AttendanceRecord.AbsenceType.UNEXCUSED},
        )
        self.assertEqual(Notification.objects.count(), 1)

    def test_absence_without_active_guardian_still_succeeds(self):
        self.guardian.is_active = False
        self.guardian.save(update_fields=["is_active"])
        _sheet, record = self.sheet_with_record()
        updated = update_attendance_record(
            record=record,
            data={"status": AttendanceRecord.Status.ABSENT,
                  "absence_type": AttendanceRecord.AbsenceType.UNEXCUSED},
        )
        self.assertEqual(updated.status, AttendanceRecord.Status.ABSENT)
        self.assertFalse(Notification.objects.exists())

    @override_settings(FIREBASE_PUSH_ENABLED=True)
    @patch("notifications.push_services.send_notification_push", side_effect=RuntimeError("firebase down"))
    def test_firebase_failure_does_not_break_absence_update(self, _send):
        _sheet, record = self.sheet_with_record()
        with self.captureOnCommitCallbacks(execute=True):
            updated = update_attendance_record(
                record=record,
                data={"status": AttendanceRecord.Status.ABSENT,
                      "absence_type": AttendanceRecord.AbsenceType.UNEXCUSED},
            )
        self.assertEqual(updated.status, AttendanceRecord.Status.ABSENT)
        self.assertEqual(Notification.objects.count(), 1)


class PermissionMatrixTests(AttendanceFixture):
    def assert_read_access(self, user, expected):
        sheet, record = self.sheet_with_record()
        client = self.client_for(user)
        for url in (
            "/api/v1/attendance/sheets/", f"/api/v1/attendance/sheets/{sheet.pk}/",
            "/api/v1/attendance/records/", f"/api/v1/attendance/records/{record.pk}/",
        ):
            self.assertEqual(client.get(url).status_code, expected, url)
        with patch("attendance.views.timezone.localdate", return_value=self.today):
            response = client.get("/api/v1/attendance/sheets/roster/", {"section": self.section_a.pk})
        self.assertEqual(response.status_code, expected)

    def assert_write_access(self, user, expected):
        sheet, record = self.sheet_with_record()
        client = self.client_for(user)
        self.assertEqual(client.patch(
            f"/api/v1/attendance/records/{record.pk}/", {"notes": "updated"}, format="json"
        ).status_code, expected)
        self.assertEqual(client.post(
            f"/api/v1/attendance/sheets/{sheet.pk}/bulk-update/",
            {"records": [{"id": str(record.pk), "notes": "bulk"}]}, format="json",
        ).status_code, expected)
        self.assertEqual(client.post(
            f"/api/v1/attendance/sheets/{sheet.pk}/normal-departure/",
            {"departure_time": "13:00", "departure_method": "guardian"}, format="json",
        ).status_code, expected)

    def create_for_section_b(self, user):
        other = Student.objects.create(first_name="رامي", last_name="حسن", birth_date=date(2018, 1, 1), gender="male")
        enrollment = Enrollment.objects.create(
            student=other, academic_year=self.year, section=self.section_b, enrollment_date=date(2026, 1, 1)
        )
        return self.client_for(user).post(
            "/api/v1/attendance/sheets/",
            {"section": str(self.section_b.pk), "records": [{"enrollment": str(enrollment.pk), "status": "present"}]},
            format="json",
        )

    @patch("attendance.services.timezone.localdate", return_value=date(2026, 8, 16))
    def test_supervisor_has_approved_full_access(self, mocked):
        self.assert_read_access(self.supervisor, 200)
        self.assert_write_access(self.supervisor, 200)
        self.assertEqual(self.create_for_section_b(self.supervisor).status_code, 201)

    @patch("attendance.services.timezone.localdate", return_value=date(2026, 8, 16))
    def test_school_admin_has_approved_full_access(self, mocked):
        self.assert_read_access(self.school_admin, 200)
        self.assert_write_access(self.school_admin, 200)
        self.assertEqual(self.create_for_section_b(self.school_admin).status_code, 201)

    def test_teacher_is_denied_everywhere(self):
        self.assert_read_access(self.teacher, 403)
        self.assert_write_access(self.teacher, 403)
        self.assertEqual(self.client_for(self.teacher).post(
            "/api/v1/attendance/sheets/", {}, format="json"
        ).status_code, 403)

    def test_other_roles_are_denied(self):
        for user in (self.secretariat, self.tech_support, self.guardian):
            self.assert_read_access(user, 403)

    @patch("attendance.services.timezone.localdate", return_value=date(2026, 8, 16))
    def test_superuser_has_full_access(self, mocked):
        self.assert_read_access(self.superuser, 200)
        self.assert_write_access(self.superuser, 200)
        self.assertEqual(self.create_for_section_b(self.superuser).status_code, 201)


class ExistingRuleTests(AttendanceFixture):
    def test_sheet_and_record_uniqueness(self):
        sheet, _ = self.sheet_with_record()
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttendanceSheet.objects.create(section=self.section_a, attendance_date=self.today, created_by=self.supervisor)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttendanceRecord.objects.create(sheet=sheet, enrollment=self.enrollment, status="present")

    @patch("attendance.services.timezone.localdate", return_value=date(2026, 8, 14))
    def test_friday_rejected(self, mocked):
        with self.assertRaises(ValidationError):
            create_attendance_sheet(section=self.section_a, actor=self.supervisor, records=self.payload())

    @patch("attendance.services.timezone.localdate", return_value=date(2026, 8, 15))
    def test_saturday_rejected(self, mocked):
        with self.assertRaises(ValidationError):
            create_attendance_sheet(section=self.section_a, actor=self.supervisor, records=self.payload())

    @patch("attendance.services.timezone.localdate", return_value=date(2026, 8, 16))
    def test_duplicate_missing_extra_and_inactive_rosters_rejected(self, mocked):
        for records in ([], self.payload() * 2):
            with self.assertRaises(ValidationError):
                create_attendance_sheet(section=self.section_a, actor=self.supervisor, records=records)
        wrong_student = Student.objects.create(first_name="س", last_name="ص", birth_date=date(2018, 1, 1), gender="male")
        wrong = Enrollment.objects.create(
            student=wrong_student, academic_year=self.year, section=self.section_b, enrollment_date=date(2026, 1, 1)
        )
        with self.assertRaises(ValidationError):
            create_attendance_sheet(
                section=self.section_a, actor=self.supervisor,
                records=[{"enrollment": wrong, "status": "present"}],
            )
        self.student.is_active = False
        self.student.save(update_fields=["is_active", "updated_at"])
        with self.assertRaises(ValidationError):
            create_attendance_sheet(section=self.section_a, actor=self.supervisor, records=self.payload())

    def test_excused_absence_and_time_rules_remain(self):
        invalid = (
            {"status": "present", "absence_type": "excused"}, {"status": "absent"},
            {"status": "absent", "absence_type": "excused"},
            {"status": "present", "arrival_time": time(10), "departure_time": time(9)},
        )
        for item in invalid:
            with self.assertRaises(ValidationError):
                normalize_and_validate_record(item)

    def test_bulk_is_atomic(self):
        second = Student.objects.create(first_name="رامي", last_name="حسن", birth_date=date(2018, 1, 1), gender="male")
        enrollment = Enrollment.objects.create(
            student=second, academic_year=self.year, section=self.section_a, enrollment_date=date(2026, 1, 1)
        )
        sheet, first = self.sheet_with_record()
        second_record = AttendanceRecord.objects.create(sheet=sheet, enrollment=enrollment, status="present")
        with self.assertRaises(ValidationError):
            bulk_update_attendance(
                sheet=sheet, actor=self.supervisor,
                items=[{"id": first.pk, "notes": "changed"}, {"id": second_record.pk, "status": "absent"}],
            )
        first.refresh_from_db()
        self.assertEqual(first.notes, "")


class NormalizationAndDepartureTests(AttendanceFixture):
    def test_excused_absence_without_reason_returns_business_400(self):
        _, record = self.sheet_with_record()
        response = self.client_for(self.supervisor).patch(
            f"/api/v1/attendance/records/{record.pk}/",
            {"status": "absent", "absence_type": "excused"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "ATTENDANCE_RECORD_INVALID")

    def test_present_to_absent_clears_transport_data(self):
        _, record = self.sheet_with_record(
            arrival_time=time(8), arrival_method="school_bus", departure_time=time(13), departure_method="guardian"
        )
        record = update_attendance_record(record=record, data={"status": "absent", "absence_type": "unexcused"})
        self.assertIsNone(record.arrival_time)
        self.assertEqual(record.arrival_method, "")
        self.assertIsNone(record.departure_time)
        self.assertEqual(record.departure_method, "")

    def test_absent_to_present_clears_absence_data(self):
        _, record = self.sheet_with_record(
            status="absent", absence_type="excused", absence_reason="مرض", absence_reason_source="guardian"
        )
        record = update_attendance_record(record=record, data={"status": "present"})
        self.assertEqual(record.absence_type, "")
        self.assertEqual(record.absence_reason, "")
        self.assertEqual(record.absence_reason_source, "")

    @patch("attendance.services.timezone.localdate", return_value=date(2026, 8, 16))
    def test_morning_creation_discards_departure(self, mocked):
        sheet = create_attendance_sheet(
            section=self.section_a, actor=self.supervisor,
            records=self.payload(departure_time=time(13), departure_method="guardian"),
        )
        record = sheet.records.get()
        self.assertIsNone(record.departure_time)
        self.assertEqual(record.departure_method, "")

    def test_individual_special_departure_still_works(self):
        _, record = self.sheet_with_record(arrival_time=time(8))
        record = update_attendance_record(
            record=record, data={"departure_time": time(12), "departure_method": "guardian"}
        )
        self.assertEqual(record.departure_time, time(12))

    def test_normal_departure_skips_absent_and_already_departed(self):
        sheet, present = self.sheet_with_record()
        absent_student = Student.objects.create(first_name="غائب", last_name="طالب", birth_date=date(2018, 1, 1), gender="male")
        absent_enrollment = Enrollment.objects.create(
            student=absent_student, academic_year=self.year, section=self.section_a, enrollment_date=date(2026, 1, 1)
        )
        absent = AttendanceRecord.objects.create(
            sheet=sheet, enrollment=absent_enrollment, status="absent", absence_type="unexcused"
        )
        departed_student = Student.objects.create(first_name="غادر", last_name="طالب", birth_date=date(2018, 1, 1), gender="male")
        departed_enrollment = Enrollment.objects.create(
            student=departed_student, academic_year=self.year, section=self.section_a, enrollment_date=date(2026, 1, 1)
        )
        departed = AttendanceRecord.objects.create(
            sheet=sheet, enrollment=departed_enrollment, status="present", departure_time=time(12), departure_method="guardian"
        )
        affected = apply_normal_departure(
            sheet=sheet, actor=self.supervisor, departure_time=time(13), departure_method="school_bus"
        )
        self.assertEqual([record.pk for record in affected], [present.pk])
        absent.refresh_from_db()
        departed.refresh_from_db()
        self.assertIsNone(absent.departure_time)
        self.assertEqual(departed.departure_time, time(12))


class TransferRosterTests(AttendanceFixture):
    def roster_ids(self, section, target_date=None):
        return {enrollment.pk for enrollment in get_effective_attendance_roster(
            section=section, attendance_date=target_date or self.today
        )}

    def test_no_transfer_uses_current_section(self):
        self.assertIn(self.enrollment.pk, self.roster_ids(self.section_a))
        self.assertNotIn(self.enrollment.pk, self.roster_ids(self.section_b))

    def test_same_day_transfer_uses_old_section(self):
        self.log_transfer(self.section_a, self.section_b, self.local_datetime(self.today, 10))
        self.assertIn(self.enrollment.pk, self.roster_ids(self.section_a))
        self.assertNotIn(self.enrollment.pk, self.roster_ids(self.section_b))

    def test_yesterday_transfer_uses_new_section_today(self):
        self.log_transfer(self.section_a, self.section_b, self.local_datetime(date(2026, 8, 15), 10))
        self.assertIn(self.enrollment.pk, self.roster_ids(self.section_b))
        self.assertNotIn(self.enrollment.pk, self.roster_ids(self.section_a))

    def test_multiple_same_day_transfers_use_earliest_old_section(self):
        self.log_transfer(self.section_a, self.section_b, self.local_datetime(self.today, 10))
        self.log_transfer(self.section_b, self.section_c, self.local_datetime(self.today, 12))
        self.assertIn(self.enrollment.pk, self.roster_ids(self.section_a))
        self.assertNotIn(self.enrollment.pk, self.roster_ids(self.section_b))
        self.assertNotIn(self.enrollment.pk, self.roster_ids(self.section_c))

    def test_existing_record_is_untouched_after_transfer(self):
        sheet, record = self.sheet_with_record()
        self.log_transfer(self.section_a, self.section_b, self.local_datetime(self.today, 10))
        record.refresh_from_db()
        self.assertEqual(record.sheet, sheet)
        self.assertEqual(record.sheet.section, self.section_a)

    @patch("attendance.services.timezone.localdate", return_value=date(2026, 8, 16))
    def test_new_section_sheet_cannot_duplicate_transferred_student(self, mocked):
        self.log_transfer(self.section_a, self.section_b, self.local_datetime(self.today, 10))
        resident = Student.objects.create(first_name="مقيم", last_name="ب", birth_date=date(2018, 1, 1), gender="male")
        resident_enrollment = Enrollment.objects.create(
            student=resident, academic_year=self.year, section=self.section_b, enrollment_date=date(2026, 1, 1)
        )
        with self.assertRaises(ValidationError):
            create_attendance_sheet(
                section=self.section_b, actor=self.supervisor,
                records=[
                    {"enrollment": resident_enrollment, "status": "present"},
                    {"enrollment": self.enrollment, "status": "present"},
                ],
            )

    def test_next_day_uses_current_new_section(self):
        self.log_transfer(self.section_a, self.section_b, self.local_datetime(self.today, 10))
        self.assertIn(self.enrollment.pk, self.roster_ids(self.section_b, date(2026, 8, 17)))

    @patch("attendance.services.timezone.localdate", return_value=date(2026, 8, 16))
    def test_roster_api_matches_creation_and_has_no_side_effects(self, mocked):
        with patch("attendance.views.timezone.localdate", return_value=self.today):
            response = self.client_for(self.supervisor).get(
                "/api/v1/attendance/sheets/roster/", {"section": self.section_a.pk}
            )
        self.assertEqual(response.status_code, 200)
        item = response.data["data"][0]
        self.assertEqual(item["enrollment"], str(self.enrollment.pk))
        self.assertEqual(item["student"], str(self.student.pk))
        self.assertEqual(item["usual_arrival_method"], "school_bus")
        self.assertIsNone(item["usual_departure_method"])
        self.assertEqual(AttendanceSheet.objects.count(), 0)
        self.assertEqual(AuditLog.objects.count(), 0)
        sheet = create_attendance_sheet(section=self.section_a, actor=self.supervisor, records=self.payload())
        self.assertEqual(set(sheet.records.values_list("enrollment_id", flat=True)), {self.enrollment.pk})


class AttendanceAuditTests(AttendanceFixture):
    def attendance_audits(self):
        return AuditLog.objects.filter(module=AuditLog.Module.ATTENDANCE)

    @patch("attendance.services.timezone.localdate", return_value=date(2026, 8, 16))
    def test_create_emits_exactly_one_event_and_failed_create_none(self, mocked):
        create_attendance_sheet(section=self.section_a, actor=self.supervisor, records=self.payload())
        self.assertEqual(self.attendance_audits().count(), 1)
        event = self.attendance_audits().get()
        self.assertEqual(event.action, AuditLog.Action.CREATE)
        self.assertEqual(event.metadata["students_count"], 1)
        before = self.attendance_audits().count()
        with self.assertRaises(ValidationError):
            create_attendance_sheet(section=self.section_b, actor=self.supervisor, records=self.payload())
        self.assertEqual(self.attendance_audits().count(), before)

    def test_bulk_updates_only_changed_records_and_noop_does_not_write(self):
        second = Student.objects.create(first_name="ثان", last_name="طالب", birth_date=date(2018, 1, 1), gender="male")
        enrollment = Enrollment.objects.create(
            student=second, academic_year=self.year, section=self.section_a, enrollment_date=date(2026, 1, 1)
        )
        sheet, first = self.sheet_with_record()
        second_record = AttendanceRecord.objects.create(sheet=sheet, enrollment=enrollment, status="present")
        first_updated_at = first.updated_at
        old_timestamp = timezone.now() - timedelta(minutes=5)
        AttendanceRecord.objects.filter(pk=second_record.pk).update(
            updated_at=old_timestamp
        )
        second_record.refresh_from_db()
        second_updated_at = second_record.updated_at
        new_timestamp = old_timestamp + timedelta(minutes=1)
        with patch("attendance.services.timezone.now", return_value=new_timestamp):
            bulk_update_attendance(
                sheet=sheet, actor=self.supervisor,
                items=[{"id": first.pk, "notes": ""}, {"id": second_record.pk, "notes": "two"}],
            )
        self.assertEqual(self.attendance_audits().count(), 1)
        self.assertEqual(self.attendance_audits().get().metadata["changed_count"], 1)
        first.refresh_from_db()
        second_record.refresh_from_db()
        self.assertEqual(first.updated_at, first_updated_at)
        self.assertEqual(second_record.notes, "two")
        self.assertEqual(second_record.updated_at, new_timestamp)
        self.assertGreater(second_record.updated_at, second_updated_at)
        self.attendance_audits().delete()
        no_op_updated_at = second_record.updated_at
        later_timestamp = new_timestamp + timedelta(minutes=1)
        with patch("attendance.services.timezone.now", return_value=later_timestamp):
            bulk_update_attendance(
                sheet=sheet, actor=self.supervisor,
                items=[{"id": second_record.pk, "notes": "two"}],
            )
        second_record.refresh_from_db()
        self.assertEqual(second_record.updated_at, no_op_updated_at)
        self.assertEqual(self.attendance_audits().count(), 0)
        with self.assertRaises(ValidationError):
            bulk_update_attendance(sheet=sheet, actor=self.supervisor, items=[{"id": first.pk, "status": "absent"}])
        self.assertEqual(self.attendance_audits().count(), 0)

    def test_normal_departure_many_one_event_then_zero_none(self):
        second = Student.objects.create(first_name="ثان", last_name="طالب", birth_date=date(2018, 1, 1), gender="male")
        enrollment = Enrollment.objects.create(
            student=second, academic_year=self.year, section=self.section_a, enrollment_date=date(2026, 1, 1)
        )
        sheet, _ = self.sheet_with_record()
        AttendanceRecord.objects.create(sheet=sheet, enrollment=enrollment, status="present")
        apply_normal_departure(
            sheet=sheet, actor=self.supervisor, departure_time=time(13), departure_method="guardian"
        )
        self.assertEqual(self.attendance_audits().count(), 1)
        self.assertEqual(self.attendance_audits().get().metadata["affected_count"], 2)
        self.attendance_audits().delete()
        apply_normal_departure(
            sheet=sheet, actor=self.supervisor, departure_time=time(14), departure_method="guardian"
        )
        self.assertEqual(self.attendance_audits().count(), 0)

    def test_individual_patch_service_does_not_audit(self):
        _, record = self.sheet_with_record()
        update_attendance_record(record=record, data={"notes": "special"})
        self.assertEqual(self.attendance_audits().count(), 0)
