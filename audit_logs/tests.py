from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, Section
from audit_logs.models import AuditLog
from audit_logs.services import json_safe
from students.models import Enrollment, GuardianStudent, Student, StudentAuditLog


User = get_user_model()


class AuditAndDeletionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="test-school-admin",
            password="Strong!934",
            role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
        )
        self.client.force_authenticate(self.admin, token={"client": "web"})

    def year(self, *, active=False, offset=0):
        return AcademicYear.objects.create(
            start_date=date(2030 + offset, 9, 1), end_date=date(2031 + offset, 6, 30),
            status=AcademicYear.Status.ACTIVE if active else AcademicYear.Status.DRAFT,
        )

    def test_empty_active_year_can_be_deleted_but_used_year_is_blocked(self):
        empty = self.year(active=True)
        response = self.client.delete(f"/api/v1/academics/academic-years/{empty.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], "ACADEMIC_YEAR_DELETED")
        self.assertTrue(AuditLog.objects.filter(resource_id=str(empty.pk), action="DELETE").exists())

        used = self.year(offset=2)
        grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="صف مرتبط")
        Section.objects.create(academic_year=used, grade_level=grade, name="أ")
        before = AuditLog.objects.count()
        blocked = self.client.delete(f"/api/v1/academics/academic-years/{used.pk}/")
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(blocked.data["code"], "ACADEMIC_YEAR_DELETE_BLOCKED")
        self.assertEqual(AuditLog.objects.count(), before)

    def test_empty_section_deletes_and_used_section_is_blocked(self):
        year = self.year()
        grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="الأول")
        empty = Section.objects.create(academic_year=year, grade_level=grade, name="فارغة")
        self.assertEqual(self.client.delete(f"/api/v1/academics/sections/{empty.pk}/").status_code, 200)
        used = Section.objects.create(academic_year=year, grade_level=grade, name="مستخدمة")
        student = Student.objects.create(first_name="أحمد", last_name="علي", birth_date=date(2018, 1, 1), gender="male")
        Enrollment.objects.create(student=student, academic_year=year, section=used, enrollment_date=date(2030, 9, 1))
        response = self.client.delete(f"/api/v1/academics/sections/{used.pk}/")
        self.assertEqual(response.data["code"], "SECTION_DELETE_BLOCKED")

    def test_student_guardian_link_and_enrollment_deletion_rules(self):
        free_student = Student.objects.create(first_name="حر", last_name="طالب", birth_date=date(2018, 1, 1), gender="male")
        deleted = self.client.delete(f"/api/v1/students/students/{free_student.pk}/")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.data["code"], "STUDENT_DELETED")
        self.assertTrue(AuditLog.objects.filter(resource_id=str(free_student.pk), action="DELETE", actor=self.admin).exists())

        year = self.year()
        grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="الثاني")
        section = Section.objects.create(academic_year=year, grade_level=grade, name="أ")
        student = Student.objects.create(first_name="مرتبط", last_name="طالب", birth_date=date(2018, 1, 1), gender="male")
        enrollment = Enrollment.objects.create(student=student, academic_year=year, section=section, enrollment_date=date(2030, 9, 1))
        blocked = self.client.delete(f"/api/v1/students/students/{student.pk}/")
        self.assertEqual(blocked.data["code"], "STUDENT_DELETE_BLOCKED")
        enrollment_response = self.client.delete(f"/api/v1/students/enrollments/{enrollment.pk}/")
        self.assertEqual(enrollment_response.status_code, 200)
        self.assertEqual(enrollment_response.data["code"], "ENROLLMENT_DELETED")
        self.assertTrue(AuditLog.objects.filter(resource_id=str(enrollment.pk), action="DELETE", actor=self.admin).exists())

        guardian = User.objects.create_user(username="audit-guardian", password="Strong!934", role=User.Role.GUARDIAN)
        link = GuardianStudent.objects.create(guardian=guardian, student=student)
        response = self.client.delete(f"/api/v1/students/guardian-links/{link.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], "GUARDIAN_LINK_DELETED")
        self.assertTrue(AuditLog.objects.filter(resource_id=str(link.pk), action="DELETE", actor=self.admin).exists())
        self.assertTrue(User.objects.filter(pk=guardian.pk).exists())
        self.assertTrue(Student.objects.filter(pk=student.pk).exists())

    def test_enrollment_with_transfer_history_cannot_be_deleted(self):
        year = self.year()
        grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="الثالث")
        old_section = Section.objects.create(academic_year=year, grade_level=grade, name="أ")
        new_section = Section.objects.create(academic_year=year, grade_level=grade, name="ب")
        student = Student.objects.create(first_name="تاريخ", last_name="نقل", birth_date=date(2017, 1, 1), gender="male")
        enrollment = Enrollment.objects.create(student=student, academic_year=year, section=new_section, enrollment_date=date(2030, 9, 1))
        StudentAuditLog.objects.create(event_type=StudentAuditLog.EventType.SECTION_TRANSFER, actor=self.admin, enrollment=enrollment, old_section=old_section, new_section=new_section)
        before = AuditLog.objects.count()
        response = self.client.delete(f"/api/v1/students/enrollments/{enrollment.pk}/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "ENROLLMENT_DELETE_BLOCKED")
        self.assertEqual(AuditLog.objects.count(), before)

    def test_create_update_delete_logs_are_safe_and_persistent(self):
        created = self.client.post(
            "/api/v1/students/students/",
            {"first_name": "احمد", "last_name": "سليم", "birth_date": "2018-01-01", "gender": "male"}, format="json",
        )
        student_id = created.data["data"]["id"]
        create_log = AuditLog.objects.get(resource_id=student_id, action="CREATE")
        self.assertIn("created_record", create_log.changes)
        updated = self.client.patch(f"/api/v1/students/students/{student_id}/", {"first_name": "أحمد"}, format="json")
        self.assertEqual(updated.status_code, 200)
        update_log = AuditLog.objects.get(resource_id=student_id, action="UPDATE")
        self.assertEqual(set(update_log.changes), {"first_name"})
        deleted = self.client.delete(f"/api/v1/students/students/{student_id}/")
        self.assertEqual(deleted.status_code, 200)
        delete_log = AuditLog.objects.get(resource_id=student_id, action="DELETE")
        self.assertIn("deleted_record", delete_log.changes)
        self.assertFalse(Student.objects.filter(pk=student_id).exists())

        sanitized = json_safe({"password": "secret", "refresh_token": "secret", "name": "safe"})
        self.assertEqual(sanitized, {"name": "safe"})
