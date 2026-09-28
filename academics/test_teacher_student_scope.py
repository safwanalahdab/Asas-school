from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from students.models import Enrollment, Student
from teaching.models import TeacherAssignment

from .models import AcademicYear, GradeLevel, GradeSubject, Section, Subject
from .teacher_student_scope import (
    can_teacher_access_enrollment,
    can_teacher_access_section,
    filter_enrollments_by_teacher_scope,
    filter_sections_by_teacher_scope,
    filter_students_by_teacher_scope,
)


User = get_user_model()


class TeacherStudentScopeTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.teacher = User.objects.create_user(
            username="scope-teacher",
            password="x",
            role=User.Role.TEACHER,
            must_change_password=False,
        )
        self.other_teacher = User.objects.create_user(
            username="scope-other-teacher",
            password="x",
            role=User.Role.TEACHER,
            must_change_password=False,
        )
        self.admin = User.objects.create_user(
            username="scope-admin",
            password="x",
            role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
        )
        self.year = AcademicYear.objects.create(
            start_date=self.today - timedelta(days=100),
            end_date=self.today + timedelta(days=400),
        )
        self.grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY,
            name="Teacher scope grade",
        )
        self.subject = Subject.objects.create(name="Teacher scope subject")
        self.grade_subject = GradeSubject.objects.create(
            academic_year=self.year,
            grade_level=self.grade,
            subject=self.subject,
        )

        self.future = self.make_scope(
            "Future",
            teacher=self.teacher,
            start_date=self.today + timedelta(days=30),
        )
        self.active = self.make_scope(
            "Active",
            teacher=self.teacher,
            start_date=self.today - timedelta(days=30),
        )
        self.ends_today = self.make_scope(
            "Today",
            teacher=self.teacher,
            start_date=self.today - timedelta(days=30),
            end_date=self.today,
        )
        self.ended = self.make_scope(
            "Ended",
            teacher=self.teacher,
            start_date=self.today - timedelta(days=30),
            end_date=self.today - timedelta(days=1),
        )
        self.other = self.make_scope(
            "Other",
            teacher=self.other_teacher,
            start_date=self.today - timedelta(days=30),
        )
        self.unassigned = self.make_scope("Unassigned")

    def make_scope(
        self,
        label,
        *,
        teacher=None,
        start_date=None,
        end_date=None,
    ):
        section = Section.objects.create(
            academic_year=self.year,
            grade_level=self.grade,
            name=label,
        )
        student = Student.objects.create(
            first_name=label,
            last_name="Student",
            birth_date=self.today - timedelta(days=3650),
            gender=Student.Gender.MALE,
        )
        enrollment = Enrollment.objects.create(
            student=student,
            academic_year=self.year,
            section=section,
            enrollment_date=self.year.start_date,
        )
        assignment = None
        if teacher is not None:
            assignment = TeacherAssignment.objects.create(
                teacher=teacher,
                grade_subject=self.grade_subject,
                section=section,
                start_date=start_date,
                end_date=end_date,
            )
        return {
            "section": section,
            "student": student,
            "enrollment": enrollment,
            "assignment": assignment,
        }

    def test_future_active_and_ends_today_are_in_teacher_scope(self):
        expected_sections = {
            self.future["section"].pk,
            self.active["section"].pk,
            self.ends_today["section"].pk,
        }
        expected_enrollments = {
            self.future["enrollment"].pk,
            self.active["enrollment"].pk,
            self.ends_today["enrollment"].pk,
        }
        expected_students = {
            self.future["student"].pk,
            self.active["student"].pk,
            self.ends_today["student"].pk,
        }

        self.assertEqual(
            set(filter_sections_by_teacher_scope(
                Section.objects.all(), self.teacher
            ).values_list("pk", flat=True)),
            expected_sections,
        )
        self.assertEqual(
            set(filter_enrollments_by_teacher_scope(
                Enrollment.objects.all(), self.teacher
            ).values_list("pk", flat=True)),
            expected_enrollments,
        )
        self.assertEqual(
            set(filter_students_by_teacher_scope(
                Student.objects.all(), self.teacher
            ).values_list("pk", flat=True)),
            expected_students,
        )

    def test_ended_other_teacher_and_unassigned_are_outside_scope(self):
        for scope in (self.ended, self.other, self.unassigned):
            with self.subTest(section=scope["section"].name):
                self.assertFalse(can_teacher_access_section(
                    self.teacher, scope["section"]
                ))
                self.assertFalse(can_teacher_access_enrollment(
                    self.teacher, scope["enrollment"]
                ))

    def test_future_assignment_does_not_require_start_date_to_have_arrived(self):
        self.assertGreater(
            self.future["assignment"].start_date,
            self.today,
        )
        self.assertTrue(can_teacher_access_section(
            self.teacher, self.future["section"]
        ))
        self.assertTrue(can_teacher_access_enrollment(
            self.teacher, self.future["enrollment"]
        ))

    def test_duplicate_assignments_do_not_duplicate_scope_results(self):
        TeacherAssignment.objects.create(
            teacher=self.teacher,
            grade_subject=self.grade_subject,
            section=self.active["section"],
            start_date=self.today + timedelta(days=60),
        )

        enrollment_ids = list(filter_enrollments_by_teacher_scope(
            Enrollment.objects.all(), self.teacher
        ).values_list("pk", flat=True))
        section_ids = list(filter_sections_by_teacher_scope(
            Section.objects.all(), self.teacher
        ).values_list("pk", flat=True))
        student_ids = list(filter_students_by_teacher_scope(
            Student.objects.all(), self.teacher
        ).values_list("pk", flat=True))

        self.assertEqual(
            section_ids.count(self.active["section"].pk),
            1,
        )
        self.assertEqual(
            enrollment_ids.count(self.active["enrollment"].pk),
            1,
        )
        self.assertEqual(
            student_ids.count(self.active["student"].pk),
            1,
        )

    def test_non_teacher_scope_behavior_is_unchanged(self):
        self.assertEqual(
            filter_enrollments_by_teacher_scope(
                Enrollment.objects.all(), self.admin
            ).count(),
            Enrollment.objects.count(),
        )
        self.assertTrue(can_teacher_access_enrollment(
            self.admin, self.ended["enrollment"]
        ))
