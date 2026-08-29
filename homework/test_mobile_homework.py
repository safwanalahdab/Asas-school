from datetime import date
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from academics.models import AcademicYear, GradeLevel, GradeSubject, Section, Subject
from students.models import Enrollment, GuardianStudent, Student
from teaching.models import TeacherAssignment

from .models import Homework

User = get_user_model()


class MobileHomeworkApiTests(TestCase):
    def setUp(self):
        self.media_directory = TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        media_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        media_override.enable()
        self.addCleanup(media_override.disable)
        self.client = APIClient()
        self.guardian = User.objects.create_user(
            username="homework-guardian", password="StrongPass!493",
            role=User.Role.GUARDIAN, must_change_password=False,
        )
        self.other_guardian = User.objects.create_user(
            username="other-homework-guardian", password="StrongPass!493",
            role=User.Role.GUARDIAN, must_change_password=False,
        )
        self.teacher = User.objects.create_user(
            username="homework-teacher", first_name="أحمد", last_name="علي",
            password="StrongPass!493", role=User.Role.TEACHER,
            must_change_password=False,
        )
        self.active_year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1), end_date=date(2027, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )
        self.old_year = AcademicYear.objects.create(
            start_date=date(2025, 9, 1), end_date=date(2026, 6, 30),
            status=AcademicYear.Status.CLOSED,
        )
        self.grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="الخامس")
        self.section = Section.objects.create(
            academic_year=self.active_year, grade_level=self.grade, name="أ"
        )
        self.other_section = Section.objects.create(
            academic_year=self.active_year, grade_level=self.grade, name="ب"
        )
        self.old_section = Section.objects.create(
            academic_year=self.old_year, grade_level=self.grade, name="قديم"
        )
        self.math = Subject.objects.create(name="الرياضيات")
        self.science = Subject.objects.create(name="العلوم")
        self.math_grade = GradeSubject.objects.create(
            academic_year=self.active_year, grade_level=self.grade, subject=self.math
        )
        self.science_grade = GradeSubject.objects.create(
            academic_year=self.active_year, grade_level=self.grade, subject=self.science
        )
        self.old_grade_subject = GradeSubject.objects.create(
            academic_year=self.old_year, grade_level=self.grade, subject=self.math
        )
        self.assignment = TeacherAssignment.objects.create(
            teacher=self.teacher, grade_subject=self.math_grade, section=self.section,
            start_date=date(2026, 9, 1), end_date=date(2026, 9, 2),
        )
        self.science_assignment = TeacherAssignment.objects.create(
            teacher=self.teacher, grade_subject=self.science_grade, section=self.section,
            start_date=date(2026, 9, 1),
        )
        self.other_assignment = TeacherAssignment.objects.create(
            teacher=self.teacher, grade_subject=self.math_grade, section=self.other_section,
            start_date=date(2026, 9, 1),
        )
        self.old_assignment = TeacherAssignment.objects.create(
            teacher=self.teacher, grade_subject=self.old_grade_subject, section=self.old_section,
            start_date=date(2025, 9, 1),
        )
        self.child = Student.objects.create(
            first_name="سليم", last_name="محمد", birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )
        self.no_enrollment_child = Student.objects.create(
            first_name="ليان", last_name="محمد", birth_date=date(2016, 1, 1),
            gender=Student.Gender.FEMALE,
        )
        self.other_child = Student.objects.create(
            first_name="غريب", last_name="أسرة", birth_date=date(2015, 2, 1),
            gender=Student.Gender.MALE,
        )
        GuardianStudent.objects.create(guardian=self.guardian, student=self.child)
        GuardianStudent.objects.create(guardian=self.guardian, student=self.no_enrollment_child)
        GuardianStudent.objects.create(guardian=self.other_guardian, student=self.other_child)
        Enrollment.objects.create(
            student=self.child, academic_year=self.active_year, section=self.section,
            enrollment_date=date(2026, 9, 1),
        )
        self.visible = self.create_homework(self.assignment, "واجب ظاهر", date(2026, 10, 10))
        self.science_work = self.create_homework(self.science_assignment, "واجب علوم", date(2026, 10, 12))
        self.create_homework(self.other_assignment, "شعبة أخرى", date(2026, 10, 11))
        self.create_homework(self.old_assignment, "سنة قديمة", date(2025, 10, 10))

    def create_homework(self, assignment, title, homework_date, attachment=None):
        return Homework.objects.create(
            teacher_assignment=assignment, title=title, description="التفاصيل",
            homework_date=homework_date, due_date=homework_date,
            attachment=attachment, created_by=self.teacher,
        )

    def url(self, child=None):
        return f"/api/v1/mobile/children/{(child or self.child).id}/homework/"

    def authenticate(self, client="mobile"):
        refresh = RefreshToken.for_user(self.guardian)
        refresh["client"] = client
        refresh["token_version"] = self.guardian.token_version
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def test_returns_only_current_section_and_active_year_with_expected_fields(self):
        self.authenticate()
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["title"] for item in response.data["data"]], ["واجب علوم", "واجب ظاهر"])
        item = response.data["data"][1]
        self.assertEqual(set(item), {
            "id", "title", "description", "homework_date", "due_date", "attachment",
            "subject", "teacher", "section", "created_at",
        })
        self.assertEqual(item["subject"]["name"], "الرياضيات")
        self.assertEqual(item["teacher"]["full_name"], "أحمد علي")
        self.assertEqual(item["section"]["name"], "أ")
        self.assertIsNone(item["attachment"])

    def test_teacher_assignment_may_be_historically_ended(self):
        self.authenticate()
        titles = [x["title"] for x in self.client.get(self.url()).data["data"]]
        self.assertIn("واجب ظاهر", titles)

    def test_teacher_full_name_falls_back_to_username(self):
        fallback_teacher = User.objects.create_user(
            username="fallback-homework-teacher",
            first_name="",
            last_name="",
            password="StrongPass!493",
            role=User.Role.TEACHER,
            must_change_password=False,
        )
        assignment = TeacherAssignment.objects.create(
            teacher=fallback_teacher,
            grade_subject=self.math_grade,
            section=self.section,
            start_date=date(2026, 9, 1),
        )
        homework = self.create_homework(
            assignment,
            "واجب معلم بلا اسم",
            date(2026, 10, 15),
        )
        self.authenticate()

        response = self.client.get(self.url())
        item = next(
            result
            for result in response.data["data"]
            if result["id"] == str(homework.id)
        )

        self.assertEqual(
            item["teacher"]["full_name"],
            fallback_teacher.username,
        )

    def test_unowned_child_is_hidden_and_missing_enrollment_is_empty(self):
        self.authenticate()
        self.assertEqual(self.client.get(self.url(self.other_child)).status_code, 404)
        response = self.client.get(self.url(self.no_enrollment_child))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"], [])

    def test_child_with_historical_enrollment_only_gets_empty_homework(self):
        historical_child = Student.objects.create(
            first_name="تاريخي",
            last_name="محمد",
            birth_date=date(2015, 3, 1),
            gender=Student.Gender.MALE,
        )
        GuardianStudent.objects.create(
            guardian=self.guardian,
            student=historical_child,
            is_active=True,
        )
        Enrollment.objects.create(
            student=historical_child,
            academic_year=self.old_year,
            section=self.old_section,
            enrollment_date=date(2025, 9, 1),
        )
        self.authenticate()

        response = self.client.get(self.url(historical_child))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], "MOBILE_CHILD_HOMEWORK_RETRIEVED")
        self.assertEqual(response.data["data"], [])

    def test_date_filters_and_range_validation(self):
        self.authenticate()
        self.assertEqual(len(self.client.get(self.url(), {"date_from": "2026-10-11"}).data["data"]), 1)
        self.assertEqual(len(self.client.get(self.url(), {"date_to": "2026-10-10"}).data["data"]), 1)
        self.assertEqual(len(self.client.get(self.url(), {"date_from": "2026-10-10", "date_to": "2026-10-10"}).data["data"]), 1)
        self.assertEqual(self.client.get(self.url(), {"date_from": "2026-10-13", "date_to": "2026-10-10"}).status_code, 400)
        self.assertEqual(self.client.get(self.url(), {"date_from": "bad-date"}).status_code, 400)

    def test_subject_filter_is_validated_and_cannot_expand_scope(self):
        self.authenticate()
        response = self.client.get(self.url(), {"subject": str(self.math.id)})
        self.assertEqual([x["title"] for x in response.data["data"]], ["واجب ظاهر"])
        self.assertEqual(self.client.get(self.url(), {"subject": "invalid"}).status_code, 400)
        self.assertNotIn("شعبة أخرى", [x["title"] for x in response.data["data"]])

    def test_attachment_is_absolute_when_present(self):
        attached = self.create_homework(
            self.assignment, "مرفق", date(2026, 10, 13),
            SimpleUploadedFile("task.txt", b"task"),
        )
        self.authenticate()
        item = next(x for x in self.client.get(self.url()).data["data"] if x["id"] == str(attached.id))
        self.assertTrue(item["attachment"].startswith("http://testserver/"))

    def test_auth_password_gate_and_methods(self):
        self.assertEqual(self.client.get(self.url()).status_code, 401)
        self.authenticate(client="web")
        self.assertEqual(self.client.get(self.url()).status_code, 401)
        self.guardian.must_change_password = True
        self.guardian.save(update_fields=["must_change_password"])
        self.authenticate()
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.guardian.must_change_password = False
        self.guardian.save(update_fields=["must_change_password"])
        self.authenticate()
        for method in (
            self.client.post,
            self.client.put,
            self.client.patch,
            self.client.delete,
        ):
            response = method(self.url(), {}, format="json")
            self.assertEqual(response.status_code, 405)
            self.assertFalse(response.data["success"])
            self.assertEqual(response.data["code"], "METHOD_NOT_ALLOWED")

    def test_related_data_has_no_n_plus_one(self):
        self.create_homework(self.assignment, "إضافي", date(2026, 10, 14))
        self.authenticate()
        with self.assertNumQueries(4):
            response = self.client.get(self.url())
            self.assertEqual(response.status_code, 200)
