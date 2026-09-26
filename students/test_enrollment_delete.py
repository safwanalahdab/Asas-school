from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from academics.models import AcademicYear, GradeLevel, Section
from behavior.models import BehaviorNote

from .models import Enrollment, Student, StudentAuditLog


class EnrollmentDeleteTests(TestCase):
    blocked_detail = (
        "لا يمكن حذف التسجيل لوجود بيانات أو سجلات تاريخية مرتبطة به."
    )

    def setUp(self):
        self.admin = User.objects.create_user(
            username="enrollment-delete-admin",
            password="Strong!934",
            role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
        )
        self.client = APIClient()
        self.client.force_authenticate(
            self.admin,
            token={"client": "web"},
        )
        self.year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
        )
        self.grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY,
            name="الخامس - اختبار الحذف",
        )
        self.section_a = Section.objects.create(
            academic_year=self.year,
            grade_level=self.grade,
            name="أ",
        )
        self.section_b = Section.objects.create(
            academic_year=self.year,
            grade_level=self.grade,
            name="ب",
        )

    def make_enrollment(self, first_name):
        student = Student.objects.create(
            first_name=first_name,
            last_name="طالب",
            birth_date=date(2016, 1, 1),
            gender=Student.Gender.MALE,
        )
        return Enrollment.objects.create(
            student=student,
            academic_year=self.year,
            section=self.section_a,
            enrollment_date=date(2026, 9, 1),
        )

    def delete(self, enrollment):
        return self.client.delete(
            f"/api/v1/students/enrollments/{enrollment.pk}/"
        )

    def assert_blocked_response(self, response):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "ENROLLMENT_DELETE_BLOCKED")
        self.assertEqual(response.data["message"], self.blocked_detail)

    def test_student_audit_log_blocks_delete_with_public_error(self):
        enrollment = self.make_enrollment("سجل")
        StudentAuditLog.objects.create(
            event_type=StudentAuditLog.EventType.SECTION_TRANSFER,
            actor=self.admin,
            enrollment=enrollment,
            old_section=self.section_a,
            new_section=self.section_b,
        )

        response = self.delete(enrollment)

        self.assert_blocked_response(response)
        self.assertTrue(Enrollment.objects.filter(pk=enrollment.pk).exists())

    def test_other_protected_relation_blocks_delete_with_same_public_error(self):
        enrollment = self.make_enrollment("سلوك")
        BehaviorNote.objects.create(
            enrollment=enrollment,
            note_type=BehaviorNote.Type.POSITIVE,
            title="ملاحظة",
            description="بيانات تاريخية",
            occurred_on=date(2026, 9, 2),
            created_by=self.admin,
        )

        response = self.delete(enrollment)

        self.assert_blocked_response(response)
        self.assertTrue(Enrollment.objects.filter(pk=enrollment.pk).exists())

    def test_unrelated_enrollment_remains_deletable(self):
        enrollment = self.make_enrollment("قابل للحذف")

        response = self.delete(enrollment)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Enrollment.objects.filter(pk=enrollment.pk).exists())
