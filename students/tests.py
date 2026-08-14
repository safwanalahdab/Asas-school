from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, Section
from students.models import Enrollment, Student


User = get_user_model()


class StudentApiEnvelopeTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="student-admin", password="Strong!934",
            role=User.Role.SCHOOL_ADMIN, must_change_password=False,
        )
        self.client.force_authenticate(self.admin, token={"client": "web"})
        self.year = AcademicYear.objects.create(
            start_date=date(2025, 9, 1), end_date=date(2026, 6, 30)
        )
        self.other_year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1), end_date=date(2027, 6, 30)
        )
        self.grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY, name="الأول"
        )
        self.other_grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY, name="الثاني"
        )
        self.section = Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name="أ"
        )
        self.target = Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name="ب"
        )
        self.other_grade_section = Section.objects.create(
            academic_year=self.year, grade_level=self.other_grade, name="أ"
        )
        self.other_year_section = Section.objects.create(
            academic_year=self.other_year, grade_level=self.grade, name="أ"
        )
        self.student = Student.objects.create(
            first_name="أحمد", last_name="خالد", birth_date=date(2018, 1, 1),
            gender=Student.Gender.MALE,
        )
        self.enrollment = Enrollment.objects.create(
            student=self.student, academic_year=self.year, section=self.section,
            enrollment_date=date(2025, 9, 1),
        )

    def transfer(self, section):
        return self.client.post(
            f"/api/v1/students/enrollments/{self.enrollment.pk}/transfer/",
            {"section": str(section.pk)}, format="json",
        )

    def test_list_create_update_not_found_and_validation_envelopes(self):
        listed = self.client.get("/api/v1/students/students/")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data["code"], "STUDENTS_RETRIEVED")
        self.assertIn("results", listed.data["data"])
        self.assertNotIn("meta", listed.data["data"])
        self.assertEqual(
            listed.data["meta"]["requester_role"],
            {"code": "school_admin", "label": "إدارة المدرسة"},
        )

        invalid = self.client.post("/api/v1/students/students/", {}, format="json")
        self.assertEqual(invalid.status_code, 400)
        self.assertFalse(invalid.data["success"])
        self.assertEqual(invalid.data["code"], "VALIDATION_ERROR")
        self.assertIn("first_name", invalid.data["errors"])
        self.assertEqual(invalid.data["meta"]["requester_role"]["code"], "school_admin")
        self.assertEqual(invalid.data["errors"]["first_name"], ["هذا الحقل مطلوب."])

        created = self.client.post(
            "/api/v1/students/students/",
            {"first_name": "سارة", "last_name": "علي", "birth_date": "2018-02-01", "gender": "female"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["code"], "STUDENT_CREATED")
        student_id = created.data["data"]["id"]
        updated = self.client.patch(
            f"/api/v1/students/students/{student_id}/", {"first_name": "سلمى"}, format="json"
        )
        self.assertEqual(updated.data["code"], "STUDENT_UPDATED")
        missing = self.client.get("/api/v1/students/students/00000000-0000-0000-0000-000000000000/")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.data["code"], "NOT_FOUND")

    def test_transfer_success_and_business_rule_errors(self):
        success = self.transfer(self.target)
        self.assertEqual(success.status_code, 200)
        self.assertEqual(success.data["code"], "STUDENT_TRANSFERRED")
        self.assertTrue(success.data["success"])

        same = self.transfer(self.target)
        self.assertEqual(same.status_code, 400)
        self.assertEqual(same.data["code"], "STUDENT_ALREADY_IN_SECTION")
        self.assertIn("section", same.data["errors"])

        grade = self.transfer(self.other_grade_section)
        self.assertEqual(grade.data["code"], "SECTION_GRADE_MISMATCH")
        year = self.transfer(self.other_year_section)
        self.assertEqual(year.data["code"], "SECTION_ACADEMIC_YEAR_MISMATCH")

    def test_permission_denied_uses_public_envelope(self):
        guardian = User.objects.create_user(
            username="guardian-only", password="Strong!934",
            role=User.Role.GUARDIAN, must_change_password=False,
        )
        self.client.force_authenticate(guardian, token={"client": "web"})
        response = self.client.get("/api/v1/students/students/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "WEB_DASHBOARD_ACCESS_DENIED")
        self.assertFalse(response.data["success"])
        self.assertEqual(
            response.data["meta"]["requester_role"],
            {"code": "guardian", "label": "ولي الأمر"},
        )

    def test_supervisor_and_superuser_roles_are_exposed_in_meta(self):
        supervisor = User.objects.create_user(
            username="student-supervisor", password="Strong!934",
            role=User.Role.SUPERVISOR, must_change_password=False,
        )
        self.client.force_authenticate(supervisor, token={"client": "web"})
        response = self.client.get("/api/v1/students/students/")
        self.assertEqual(
            response.data["meta"]["requester_role"],
            {"code": "supervisor", "label": "الموجّه التربوي"},
        )
        root = User.objects.create_superuser(username="meta-root", password="RootStrong!934")
        self.client.force_authenticate(root, token={"client": "web"})
        response = self.client.get("/api/v1/students/students/")
        self.assertEqual(
            response.data["meta"]["requester_role"],
            {"code": "superuser", "label": "مدير النظام"},
        )
