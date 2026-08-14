from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, GradeSubject, Section, Subject
from teaching.models import TeacherAssignment
from audit_logs.models import AuditLog


User = get_user_model()


class TeacherAssignmentEnvelopeTests(TestCase):
    def test_end_assignment_and_reject_ending_twice(self):
        admin = User.objects.create_user(username="admin-t", password="Strong!934", role=User.Role.SCHOOL_ADMIN, must_change_password=False)
        teacher = User.objects.create_user(username="teacher-t", password="Strong!934", role=User.Role.TEACHER, must_change_password=False)
        year = AcademicYear.objects.create(start_date=date(2025, 9, 1), end_date=date(2026, 6, 30))
        grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="الأول")
        section = Section.objects.create(academic_year=year, grade_level=grade, name="أ")
        subject = Subject.objects.create(name="الرياضيات")
        grade_subject = GradeSubject.objects.create(academic_year=year, grade_level=grade, subject=subject)
        assignment = TeacherAssignment.objects.create(teacher=teacher, grade_subject=grade_subject, section=section, start_date=date(2025, 9, 1))
        client = APIClient()
        client.force_authenticate(admin, token={"client": "web"})
        url = f"/api/v1/teaching/assignments/{assignment.pk}/end/"

        ended = client.post(url, {"end_date": "2025-12-01"}, format="json")
        self.assertEqual(ended.status_code, 200)
        self.assertTrue(ended.data["success"])
        self.assertEqual(ended.data["code"], "TEACHER_ASSIGNMENT_ENDED")
        self.assertIn("data", ended.data)

        repeated = client.post(url, {"end_date": "2025-12-02"}, format="json")
        self.assertEqual(repeated.status_code, 400)
        self.assertFalse(repeated.data["success"])
        self.assertEqual(repeated.data["code"], "TEACHER_ASSIGNMENT_ALREADY_ENDED")
        self.assertIn("end_date", repeated.data["errors"])

        other_section = Section.objects.create(
            academic_year=year, grade_level=grade, name="ب"
        )
        outside_year = client.post(
            "/api/v1/teaching/assignments/",
            {
                "teacher": str(teacher.pk),
                "grade_subject": str(grade_subject.pk),
                "section": str(other_section.pk),
                "start_date": "2025-08-01",
            },
            format="json",
        )
        self.assertEqual(outside_year.status_code, 400)
        self.assertEqual(
            outside_year.data["errors"]["start_date"],
            ["يجب أن يكون تاريخ بداية التكليف ضمن حدود السنة الدراسية."],
        )
        self.assertNotEqual(
            outside_year.data["errors"]["start_date"],
            ["القيمة المدخلة غير صحيحة."],
        )
        self.assertEqual(outside_year.data["meta"]["requester_role"]["code"], "school_admin")

    def test_reopen_and_delete_assignment(self):
        admin = User.objects.create_user(username="test-school-admin", password="Strong!934", role=User.Role.SCHOOL_ADMIN, must_change_password=False)
        teacher = User.objects.create_user(username="teacher-r", password="Strong!934", role=User.Role.TEACHER, must_change_password=False)
        year = AcademicYear.objects.create(start_date=date(2027, 9, 1), end_date=date(2028, 6, 30))
        grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="الثاني")
        section = Section.objects.create(academic_year=year, grade_level=grade, name="ب")
        subject = Subject.objects.create(name="العلوم")
        plan = GradeSubject.objects.create(academic_year=year, grade_level=grade, subject=subject)
        assignment = TeacherAssignment.objects.create(teacher=teacher, grade_subject=plan, section=section, start_date=date(2027, 9, 1), end_date=date(2027, 12, 1))
        client = APIClient()
        client.force_authenticate(admin, token={"client": "web"})
        url = f"/api/v1/teaching/assignments/{assignment.pk}/reopen/"
        response = client.post(url, {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], "TEACHER_ASSIGNMENT_REOPENED")
        assignment.refresh_from_db()
        self.assertIsNone(assignment.end_date)
        self.assertTrue(AuditLog.objects.filter(resource_id=str(assignment.pk), action="REOPEN", actor=admin).exists())
        deleted = client.delete(f"/api/v1/teaching/assignments/{assignment.pk}/")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.data["code"], "TEACHER_ASSIGNMENT_DELETED")
        self.assertTrue(AuditLog.objects.filter(resource_id=str(assignment.pk), action="DELETE", actor=admin).exists())

    def test_reopen_is_blocked_when_it_would_overlap(self):
        admin = User.objects.create_user(username="test-school-admin", password="Strong!934", role=User.Role.SCHOOL_ADMIN, must_change_password=False)
        teacher = User.objects.create_user(username="teacher-o", password="Strong!934", role=User.Role.TEACHER, must_change_password=False)
        year = AcademicYear.objects.create(start_date=date(2029, 9, 1), end_date=date(2030, 6, 30))
        grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="الثالث")
        section = Section.objects.create(academic_year=year, grade_level=grade, name="ج")
        subject = Subject.objects.create(name="اللغة العربية")
        plan = GradeSubject.objects.create(academic_year=year, grade_level=grade, subject=subject)
        ended = TeacherAssignment.objects.create(teacher=teacher, grade_subject=plan, section=section, start_date=date(2029, 9, 1), end_date=date(2029, 10, 1))
        TeacherAssignment.objects.create(teacher=teacher, grade_subject=plan, section=section, start_date=date(2029, 10, 2))
        client = APIClient()
        client.force_authenticate(admin, token={"client": "web"})
        response = client.post(f"/api/v1/teaching/assignments/{ended.pk}/reopen/", {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "VALIDATION_ERROR")
        ended.refresh_from_db()
        self.assertEqual(ended.end_date, date(2029, 10, 1))
