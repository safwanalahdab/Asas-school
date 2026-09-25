from datetime import date, datetime
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from academics.models import AcademicYear, GradeLevel, Section
from students.models import Enrollment, Student

from .models import StudentPointEntry


User = get_user_model()


class StudentPointEntryModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.creator = User.objects.create_user(
            username="student-points-creator",
            role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
        )
        academic_year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )
        grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY,
            name="Student points grade",
        )
        section = Section.objects.create(
            academic_year=academic_year,
            grade_level=grade,
            name="A",
        )
        student = Student.objects.create(
            first_name="Point",
            last_name="Student",
            birth_date=date(2017, 1, 1),
            gender=Student.Gender.MALE,
        )
        cls.enrollment = Enrollment.objects.create(
            student=student,
            academic_year=academic_year,
            section=section,
            enrollment_date=date(2026, 9, 1),
        )

    def entry(self, **overrides):
        values = {
            "enrollment": self.enrollment,
            "points": 10,
            "note": "مشاركة مميزة في الصف.",
            "occurred_on": date(2026, 9, 10),
            "created_by": self.creator,
        }
        values.update(overrides)
        return StudentPointEntry(**values)

    def test_valid_student_point_entry_is_created(self):
        entry = self.entry()

        entry.full_clean()
        entry.save()

        self.assertIsNotNone(entry.pk)
        self.assertEqual(entry.enrollment, self.enrollment)
        self.assertEqual(entry.points, 10)

    def test_points_one_is_accepted(self):
        entry = self.entry(points=1)

        entry.full_clean()

    def test_points_one_hundred_is_accepted(self):
        entry = self.entry(points=100)

        entry.full_clean()

    def test_points_zero_is_rejected_by_model_validation(self):
        with self.assertRaises(ValidationError):
            self.entry(points=0).full_clean()

    def test_negative_points_are_rejected_by_model_validation(self):
        with self.assertRaises(ValidationError):
            self.entry(points=-1).full_clean()

    def test_points_above_one_hundred_are_rejected_by_model_validation(self):
        with self.assertRaises(ValidationError):
            self.entry(points=101).full_clean()

    def test_empty_note_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.entry(note="").full_clean()

    def test_whitespace_only_note_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.entry(note="  \t\n  ").full_clean()

    def test_default_ordering_is_deterministic(self):
        older = self.entry(
            id=UUID("00000000-0000-0000-0000-000000000004"),
            occurred_on=date(2026, 9, 9),
        )
        same_time_low_id = self.entry(
            id=UUID("00000000-0000-0000-0000-000000000001"),
        )
        same_time_high_id = self.entry(
            id=UUID("00000000-0000-0000-0000-000000000002"),
        )
        newest = self.entry(
            id=UUID("00000000-0000-0000-0000-000000000003"),
        )
        StudentPointEntry.objects.bulk_create(
            [older, same_time_low_id, same_time_high_id, newest]
        )
        shared_time = timezone.make_aware(datetime(2026, 9, 10, 8, 0))
        newest_time = timezone.make_aware(datetime(2026, 9, 10, 9, 0))
        StudentPointEntry.objects.filter(
            pk__in=[same_time_low_id.pk, same_time_high_id.pk]
        ).update(created_at=shared_time)
        StudentPointEntry.objects.filter(pk=newest.pk).update(
            created_at=newest_time
        )

        actual_ids = list(
            StudentPointEntry.objects.values_list("id", flat=True)
        )

        self.assertEqual(
            actual_ids,
            [
                newest.pk,
                same_time_high_id.pk,
                same_time_low_id.pk,
                older.pk,
            ],
        )

    def test_database_check_constraint_rejects_out_of_range_points(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StudentPointEntry.objects.create(
                    enrollment=self.enrollment,
                    points=0,
                    note="يتجاوز الاختبار model validation عمدًا.",
                    occurred_on=date(2026, 9, 10),
                    created_by=self.creator,
                )
