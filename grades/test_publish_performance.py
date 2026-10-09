from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from accounts.models import User
from academics.models import (
    AcademicYear, GradeLevel, GradeSubject, Section, Subject, SupervisorScope,
    SupervisorScopeStage, Term,
)
from students.models import Enrollment, Student

from .models import Assessment, AssessmentSection, StudentScore
from .services import create_assessment, create_assessments_for_grade
from .supervisor_scope import require_assessment, require_assessments


BASE = "/api/v1/grades/assessments/"
SCOPE_TABLE = 'FROM "academics_supervisor_scope"'
ASSESSMENT_DATE = date(2026, 2, 1)


class PublishPerformanceTestBase(TestCase):
    def setUp(self):
        self.year = AcademicYear.objects.create(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        self.term = Term.objects.create(
            academic_year=self.year, number=Term.Number.FIRST,
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        )
        self.subject = Subject.objects.create(name="Publish perf subject")
        self.admin = self.make_user("publish-admin", User.Role.SCHOOL_ADMIN)
        self.supervisor = self.make_user("publish-supervisor", User.Role.SUPERVISOR)
        scope = SupervisorScope.objects.create(
            supervisor=self.supervisor, scope_type=SupervisorScope.ScopeType.SELECTED_STAGES,
        )
        SupervisorScopeStage.objects.create(scope=scope, stage=GradeLevel.Stage.PRIMARY)
        self.client = APIClient()
        self.counter = 0

    def make_user(self, username, role):
        user = User.objects.create_user(username=username, password="x", role=role, must_change_password=False)
        user.user_permissions.add(*Permission.objects.filter(content_type__app_label="grades"))
        return user

    def next_name(self, prefix):
        self.counter += 1
        return f"{prefix}-{self.counter:03d}"

    def grade(self, section_count, stage=GradeLevel.Stage.PRIMARY):
        grade = GradeLevel.objects.create(stage=stage, name=self.next_name("Grade"))
        sections = [
            Section.objects.create(academic_year=self.year, grade_level=grade, name=self.next_name("Section"))
            for _ in range(section_count)
        ]
        plan = GradeSubject.objects.create(academic_year=self.year, grade_level=grade, subject=self.subject)
        return grade, sections, plan

    def grade_assessments(self, plan, count):
        return [
            create_assessments_for_grade(
                grade_subject=plan, term=self.term, title=self.next_name("Grade exam"),
                max_score=Decimal("20"), assessment_date=ASSESSMENT_DATE, actor=self.admin,
            )
            for _ in range(count)
        ]

    def section_assessments(self, section, plan, count):
        return [
            create_assessment(
                section=section, grade_subject=plan, term=self.term, title=self.next_name("Section exam"),
                max_score=Decimal("20"), assessment_date=ASSESSMENT_DATE, actor=self.admin,
            )
            for _ in range(count)
        ]

    def enroll(self, section):
        student = Student.objects.create(
            first_name=self.next_name("Student"), last_name="Perf",
            birth_date=date(2018, 1, 1), gender=Student.Gender.MALE,
        )
        return Enrollment.objects.create(
            student=student, academic_year=self.year, section=section, enrollment_date=date(2026, 1, 5),
        )

    def request(self, user, method, path, payload):
        self.client.force_authenticate(user, token={"client": "web"})
        with CaptureQueriesContext(connection) as ctx:
            if method == "post":
                response = self.client.post(BASE + path, payload, format="json")
            else:
                response = self.client.get(BASE + path, payload)
        return response, ctx.captured_queries


class PublishSectionQueryTests(PublishPerformanceTestBase):
    def publish_section(self, user, assessment_count):
        _, (section,), plan = self.grade(1)
        self.section_assessments(section, plan, assessment_count)
        response, queries = self.request(
            user, "post", "publish-section/", {"section": str(section.id), "term": str(self.term.id)},
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["published_count"], assessment_count)
        return queries

    def assert_constant(self, user):
        self.publish_section(user, 1)  # warm-up
        small = self.publish_section(user, 2)
        large = self.publish_section(user, 8)
        self.assertEqual(len(large), len(small))
        return large

    def test_admin_query_count_does_not_grow_with_assessments(self):
        self.assert_constant(self.admin)

    def test_supervisor_query_count_does_not_grow_with_assessments(self):
        queries = self.assert_constant(self.supervisor)
        self.assertEqual(sum(SCOPE_TABLE in query["sql"] for query in queries), 1)


class PublishGradeQueryTests(PublishPerformanceTestBase):
    def publish_grade(self, user, section_count, assessment_count):
        grade, _, plan = self.grade(section_count)
        self.grade_assessments(plan, assessment_count)
        response, queries = self.request(
            user, "post", "publish-grade/", {"grade_level": str(grade.id), "term": str(self.term.id)},
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["published_count"], section_count * assessment_count)
        return queries

    def assert_constant(self, user):
        self.publish_grade(user, 1, 1)  # warm-up
        small = self.publish_grade(user, 1, 2)
        large = self.publish_grade(user, 3, 8)
        self.assertEqual(len(large), len(small))
        return large

    def test_admin_query_count_does_not_grow_with_links(self):
        self.assert_constant(self.admin)

    def test_supervisor_query_count_does_not_grow_with_links(self):
        queries = self.assert_constant(self.supervisor)
        self.assertEqual(sum(SCOPE_TABLE in query["sql"] for query in queries), 1)

    def test_supervisor_inconsistent_assessment_still_blocks_publishing(self):
        grade, (section,), plan = self.grade(1)
        assessment, = self.grade_assessments(plan, 1)
        self.grade_assessments(plan, 2)
        _, (other_section,), _ = self.grade(1, stage=GradeLevel.Stage.PREPARATORY)
        AssessmentSection.objects.create(assessment=assessment, section=other_section)

        response, _ = self.request(
            self.supervisor, "post", "publish-grade/", {"grade_level": str(grade.id), "term": str(self.term.id)},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "SUPERVISOR_ACADEMIC_SCOPE_DENIED")
        self.assertFalse(AssessmentSection.objects.filter(status=AssessmentSection.Status.PUBLISHED).exists())

        response, _ = self.request(
            self.supervisor, "post", "publish-section/", {"section": str(section.id), "term": str(self.term.id)},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(AssessmentSection.objects.filter(status=AssessmentSection.Status.PUBLISHED).exists())


class StudentResultsQueryTests(PublishPerformanceTestBase):
    def setUp(self):
        super().setUp()
        _, (self.section,), self.plan = self.grade(1)
        self.enrollment = self.enroll(self.section)

    def add_scored_assessments(self, count):
        for assessment in self.grade_assessments(self.plan, count):
            StudentScore.objects.create(
                assessment=assessment, enrollment=self.enrollment, recorded_section=self.section,
                score=Decimal("10"), updated_by=self.admin,
            )

    def student_results(self):
        return self.request(
            self.supervisor, "get", "student-results/",
            {"enrollment": str(self.enrollment.id), "term": str(self.term.id)},
        )

    def test_supervisor_query_count_does_not_grow_with_assessments(self):
        self.add_scored_assessments(2)
        self.student_results()  # warm-up
        response, small = self.student_results()
        self.assertEqual(response.status_code, 200, response.data)
        self.add_scored_assessments(6)
        response, large = self.student_results()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(large), len(small))
        subject, = response.data["data"]["subjects"]
        self.assertEqual(len(subject["assessments"]), 8)

    def test_inconsistent_assessment_still_returns_403(self):
        self.add_scored_assessments(2)
        assessment, = self.grade_assessments(self.plan, 1)
        _, (other_section,), _ = self.grade(1, stage=GradeLevel.Stage.PREPARATORY)
        AssessmentSection.objects.create(assessment=assessment, section=other_section)
        response, _ = self.student_results()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "SUPERVISOR_ACADEMIC_SCOPE_DENIED")


class CreateForGradeQueryTests(PublishPerformanceTestBase):
    def create_for_grade(self, user, section_count, existing_assessments=0):
        _, sections, plan = self.grade(section_count)
        self.grade_assessments(plan, existing_assessments)
        response, queries = self.request(user, "post", "create-for-grade/", {
            "grade_subject": str(plan.id), "term": str(self.term.id), "title": self.next_name("Exam"),
            "max_score": "20", "assessment_date": ASSESSMENT_DATE.isoformat(),
        })
        self.assertEqual(response.status_code, 201, response.data)
        return response, sections, queries

    def test_scope_loads_do_not_grow_with_sections(self):
        _, _, small = self.create_for_grade(self.supervisor, 1)
        _, _, large = self.create_for_grade(self.supervisor, 4)
        self.assertEqual(
            sum(SCOPE_TABLE in query["sql"] for query in large),
            sum(SCOPE_TABLE in query["sql"] for query in small),
        )

    def test_query_count_does_not_grow_with_sections_or_assessments(self):
        for user in (self.admin, self.supervisor):
            with self.subTest(user=user.username):
                self.create_for_grade(user, 1)  # warm-up
                _, _, small = self.create_for_grade(user, 1, existing_assessments=1)
                _, _, large = self.create_for_grade(user, 4, existing_assessments=5)
                # Validation, the single bulk insert and the response reload are all
                # batched, so neither sections nor existing assessments add queries.
                self.assertEqual(len(large), len(small))
                self.assertEqual(
                    sum('FROM "academics_section"' in query["sql"] for query in large),
                    sum('FROM "academics_section"' in query["sql"] for query in small),
                )

    def test_response_lists_every_section_in_name_order(self):
        response, sections, _ = self.create_for_grade(self.admin, 4)
        data = response.data["data"]
        expected = sorted(sections, key=lambda section: section.name)
        self.assertEqual([item["section"] for item in data["sections"]], [section.id for section in expected])
        self.assertEqual([item["name"] for item in data["sections"]], [section.name for section in expected])
        for item in data["sections"]:
            self.assertEqual(item["status"], AssessmentSection.Status.DRAFT)
            self.assertIsNone(item["published_by_username"])
            self.assertIsNone(item["schedule_published_by_username"])
        self.assertEqual(data["created_by_username"], self.admin.username)
        self.assertEqual(data["subject_display"], self.subject.name)
        self.assertEqual(
            set(data),
            {
                "id", "academic_year", "academic_year_display", "grade_level", "grade_level_display",
                "sections", "grade_subject", "subject", "subject_display", "term", "term_display",
                "title", "max_score", "assessment_date", "created_by", "created_by_username",
                "created_at", "updated_at",
            },
        )


class RequireAssessmentsEquivalenceTests(PublishPerformanceTestBase):
    """The batched helper must allow and deny exactly like require_assessment."""

    def setUp(self):
        super().setUp()
        _, (self.primary_section,), primary_plan = self.grade(1)
        _, (self.other_section,), other_plan = self.grade(1, stage=GradeLevel.Stage.PREPARATORY)
        self.inside, = self.grade_assessments(primary_plan, 1)
        self.outside, = self.grade_assessments(other_plan, 1)
        self.mismatched_link, = self.grade_assessments(primary_plan, 1)
        AssessmentSection.objects.create(assessment=self.mismatched_link, section=self.other_section)
        self.unlinked_score, = self.grade_assessments(primary_plan, 1)
        StudentScore.objects.create(
            assessment=self.unlinked_score, enrollment=self.enroll(self.other_section),
            recorded_section=self.other_section, score=Decimal("5"), updated_by=self.admin,
        )

    def allowed(self, check, user, assessments):
        try:
            check(user, assessments)
        except PermissionDenied as error:
            self.assertEqual(error.detail["code"], "SUPERVISOR_ACADEMIC_SCOPE_DENIED")
            self.assertEqual(error.detail["detail"], "المورد المحدد خارج نطاق مراحل الموجّه.")
            return False
        return True

    def test_single_assessment_decisions_match(self):
        cases = {
            "inside": self.inside, "outside stage": self.outside,
            "mismatched link": self.mismatched_link, "unlinked score": self.unlinked_score,
        }
        for user in (self.admin, self.supervisor):
            for name, assessment in cases.items():
                with self.subTest(user=user.username, case=name):
                    assessment = Assessment.objects.select_related("grade_subject__grade_level").get(pk=assessment.pk)
                    self.assertEqual(
                        self.allowed(lambda u, a: require_assessments(u, [a]), user, assessment),
                        self.allowed(require_assessment, user, assessment),
                    )

    def test_any_denied_assessment_denies_the_batch(self):
        self.assertTrue(self.allowed(require_assessments, self.supervisor, [self.inside]))
        self.assertFalse(self.allowed(require_assessments, self.supervisor, [self.inside, self.unlinked_score]))
        self.assertTrue(self.allowed(require_assessments, self.supervisor, []))

    def test_non_supervisors_never_evaluate_the_assessments(self):
        with CaptureQueriesContext(connection) as ctx:
            require_assessments(self.admin, Assessment.objects.all())
        self.assertEqual(len(ctx.captured_queries), 0)
