import uuid
from datetime import date

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from academics.models import (
    AcademicYear, GradeLevel, GradeSubject, Section, Subject, SupervisorScope,
    SupervisorScopeStage,
)
from students.models import Enrollment, Student
from teaching.models import TeacherAssignment

from .models import BehaviorNote


class BehaviorNoteFilterTests(TestCase):
    """BehaviorNoteFilter narrows the already-scoped notes list only."""

    url = "/api/v1/behavior/notes/"

    @classmethod
    def setUpTestData(cls):
        cls.admin = cls.make_user("behavior-filter-admin", User.Role.SCHOOL_ADMIN)
        cls.other_author = cls.make_user("behavior-filter-author", User.Role.SCHOOL_ADMIN)
        cls.supervisor = cls.make_user("behavior-filter-supervisor", User.Role.SUPERVISOR)
        scope = SupervisorScope.objects.create(
            supervisor=cls.supervisor, scope_type=SupervisorScope.ScopeType.SELECTED_STAGES,
        )
        SupervisorScopeStage.objects.create(scope=scope, stage=GradeLevel.Stage.PRIMARY)
        cls.teacher = cls.make_user("behavior-filter-teacher", User.Role.TEACHER)

        year = AcademicYear.objects.create(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        primary = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="Filter primary")
        preparatory = GradeLevel.objects.create(stage=GradeLevel.Stage.PREPARATORY, name="Filter preparatory")
        cls.section_a = Section.objects.create(academic_year=year, grade_level=primary, name="A")
        cls.section_b = Section.objects.create(academic_year=year, grade_level=primary, name="B")
        preparatory_section = Section.objects.create(academic_year=year, grade_level=preparatory, name="A")
        TeacherAssignment.objects.create(
            teacher=cls.teacher,
            grade_subject=GradeSubject.objects.create(
                academic_year=year, grade_level=primary, subject=Subject.objects.create(name="Filter subject"),
            ),
            section=cls.section_a,
            start_date=date(2026, 1, 1),
        )

        cls.enrollment_a = cls.make_enrollment(year, cls.section_a, "Alpha")
        cls.enrollment_b = cls.make_enrollment(year, cls.section_b, "Beta")
        cls.preparatory_enrollment = cls.make_enrollment(year, preparatory_section, "Gamma")

        positive, negative = BehaviorNote.Type.POSITIVE, BehaviorNote.Type.NEGATIVE
        cls.a_positive_early = cls.note(cls.enrollment_a, positive, date(2026, 3, 1))
        cls.a_negative_mid = cls.note(cls.enrollment_a, negative, date(2026, 3, 10))
        cls.b_positive_mid = cls.note(cls.enrollment_b, positive, date(2026, 3, 10), author=cls.other_author)
        cls.b_negative_late = cls.note(cls.enrollment_b, negative, date(2026, 3, 20))
        cls.preparatory_positive = cls.note(cls.preparatory_enrollment, positive, date(2026, 3, 10))

        view = Permission.objects.get(content_type__app_label="behavior", codename="view_behaviornote")
        for user in (cls.admin, cls.supervisor, cls.teacher):
            user.user_permissions.add(view)

    @classmethod
    def make_user(cls, username, role):
        return User.objects.create_user(username=username, password="x", role=role, must_change_password=False)

    @classmethod
    def make_enrollment(cls, year, section, first_name):
        student = Student.objects.create(
            first_name=first_name, last_name="Filter", birth_date=date(2016, 1, 1), gender=Student.Gender.MALE,
        )
        return Enrollment.objects.create(
            student=student, academic_year=year, section=section, enrollment_date=date(2026, 1, 1),
        )

    @classmethod
    def note(cls, enrollment, note_type, occurred_on, *, author=None):
        return BehaviorNote.objects.create(
            enrollment=enrollment, note_type=note_type, title=f"{note_type} {occurred_on}",
            description="Description", occurred_on=occurred_on, created_by=author or cls.admin,
        )

    def get(self, user, params):
        client = APIClient()
        client.force_authenticate(user, token={"client": "web"})
        return client.get(self.url, params)

    def ids(self, user, params):
        response = self.get(user, params)
        self.assertEqual(response.status_code, 200, response.data)
        return {row["id"] for row in response.data["data"]["results"]}

    @staticmethod
    def expected(*notes):
        return {str(note.pk) for note in notes}

    def test_note_type_filter(self):
        self.assertEqual(
            self.ids(self.admin, {"note_type": "positive"}),
            self.expected(self.a_positive_early, self.b_positive_mid, self.preparatory_positive),
        )
        self.assertEqual(
            self.ids(self.admin, {"note_type": "negative"}),
            self.expected(self.a_negative_mid, self.b_negative_late),
        )

    def test_enrollment_filter(self):
        self.assertEqual(
            self.ids(self.admin, {"enrollment": str(self.enrollment_a.pk)}),
            self.expected(self.a_positive_early, self.a_negative_mid),
        )

    def test_created_by_filter(self):
        self.assertEqual(
            self.ids(self.admin, {"created_by": str(self.other_author.pk)}),
            self.expected(self.b_positive_mid),
        )

    def test_occurred_date_filters_are_inclusive(self):
        self.assertEqual(
            self.ids(self.admin, {"occurred_from": "2026-03-10"}),
            self.expected(self.a_negative_mid, self.b_positive_mid, self.b_negative_late, self.preparatory_positive),
        )
        self.assertEqual(
            self.ids(self.admin, {"occurred_to": "2026-03-10"}),
            self.expected(self.a_positive_early, self.a_negative_mid, self.b_positive_mid, self.preparatory_positive),
        )
        self.assertEqual(
            self.ids(self.admin, {"occurred_from": "2026-03-10", "occurred_to": "2026-03-10"}),
            self.expected(self.a_negative_mid, self.b_positive_mid, self.preparatory_positive),
        )

    def test_filters_combine(self):
        self.assertEqual(
            self.ids(self.admin, {
                "enrollment": str(self.enrollment_b.pk), "note_type": "negative", "occurred_from": "2026-03-15",
            }),
            self.expected(self.b_negative_late),
        )

    def test_invalid_values_are_rejected(self):
        cases = {
            "note_type": "neutral",
            "enrollment": "not-a-uuid",
            "occurred_from": "not-a-date",
            "occurred_to": "2026-13-40",
            "created_by": str(uuid.uuid4()),
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                response = self.get(self.admin, {field: value})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data["code"], "VALIDATION_ERROR")
                self.assertIn(field, response.data["errors"])
        response = self.get(self.admin, {"enrollment": str(uuid.uuid4())})
        self.assertEqual(response.status_code, 400)
        self.assertIn("enrollment", response.data["errors"])

    def test_supervisor_filters_stay_inside_stage_scope(self):
        self.assertEqual(
            self.ids(self.supervisor, {"note_type": "positive"}),
            self.expected(self.a_positive_early, self.b_positive_mid),
        )
        self.assertEqual(
            self.ids(self.supervisor, {"enrollment": str(self.preparatory_enrollment.pk)}),
            set(),
        )
        self.assertEqual(
            self.ids(self.supervisor, {"occurred_from": "2026-03-10", "occurred_to": "2026-03-10"}),
            self.expected(self.a_negative_mid, self.b_positive_mid),
        )

    def test_teacher_filters_stay_inside_assigned_sections(self):
        self.assertEqual(
            self.ids(self.teacher, {"note_type": "positive"}),
            self.expected(self.a_positive_early),
        )
        self.assertEqual(self.ids(self.teacher, {"enrollment": str(self.enrollment_b.pk)}), set())
        self.assertEqual(
            self.ids(self.teacher, {"enrollment": str(self.enrollment_a.pk)}),
            self.expected(self.a_positive_early, self.a_negative_mid),
        )
