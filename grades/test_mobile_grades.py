from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from academics.models import AcademicYear, GradeLevel, GradeSubject, Section, Subject, Term
from students.models import Enrollment, GuardianStudent, Student, StudentAuditLog

from .models import Assessment, AssessmentSection, StudentScore

User = get_user_model()


def collect_dictionary_keys(value):
    keys = set()
    if isinstance(value, dict):
        keys.update(value.keys())
        for nested_value in value.values():
            keys.update(collect_dictionary_keys(nested_value))
    elif isinstance(value, (list, tuple)):
        for nested_value in value:
            keys.update(collect_dictionary_keys(nested_value))
    return keys


class MobileGradesApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.guardian = User.objects.create_user(
            username="grades-guardian", password="StrongPass!493",
            role=User.Role.GUARDIAN, must_change_password=False,
        )
        self.other_guardian = User.objects.create_user(
            username="other-grades-guardian", password="StrongPass!493",
            role=User.Role.GUARDIAN, must_change_password=False,
        )
        self.teacher = User.objects.create_user(
            username="grades-teacher", password="StrongPass!493",
            role=User.Role.TEACHER, must_change_password=False,
        )
        self.year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1), end_date=date(2027, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )
        self.old_year = AcademicYear.objects.create(
            start_date=date(2025, 9, 1), end_date=date(2026, 6, 30),
            status=AcademicYear.Status.CLOSED,
        )
        self.term_one = Term.objects.create(
            academic_year=self.year, number=Term.Number.FIRST,
            start_date=date(2026, 9, 1), end_date=date(2027, 1, 15),
        )
        self.term_two = Term.objects.create(
            academic_year=self.year, number=Term.Number.SECOND,
            start_date=date(2027, 1, 16), end_date=date(2027, 6, 30),
        )
        self.old_term = Term.objects.create(
            academic_year=self.old_year, number=Term.Number.FIRST,
            start_date=date(2025, 9, 1), end_date=date(2026, 1, 15),
        )
        self.grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY, name="الخامس"
        )
        self.section_a = Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name="أ"
        )
        self.section_b = Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name="ب"
        )
        self.old_section = Section.objects.create(
            academic_year=self.old_year, grade_level=self.grade, name="قديم"
        )
        self.math = Subject.objects.create(name="الرياضيات")
        self.science = Subject.objects.create(name="العلوم")
        self.math_plan = GradeSubject.objects.create(
            academic_year=self.year, grade_level=self.grade, subject=self.math
        )
        self.science_plan = GradeSubject.objects.create(
            academic_year=self.year, grade_level=self.grade, subject=self.science
        )
        self.child, self.enrollment = self.create_child(
            guardian=self.guardian, first_name="أحمد", section=self.section_a
        )
        self.other_child, _ = self.create_child(
            guardian=self.other_guardian, first_name="غريب", section=self.section_a
        )
        self.no_enrollment_child, _ = self.create_child(
            guardian=self.guardian, first_name="بلا تسجيل", section=None
        )

    def create_child(self, *, guardian, first_name, section):
        student = Student.objects.create(
            first_name=first_name, last_name="محمد", birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )
        GuardianStudent.objects.create(guardian=guardian, student=student)
        enrollment = None
        if section is not None:
            enrollment = Enrollment.objects.create(
                student=student, academic_year=section.academic_year,
                section=section, enrollment_date=section.academic_year.start_date,
            )
        return student, enrollment

    def create_assessment(
        self, *, title, plan=None, term=None, when=date(2026, 10, 10),
        max_score="20.00", section_statuses=None,
    ):
        assessment = Assessment.objects.create(
            grade_subject=plan or self.math_plan, term=term or self.term_one,
            title=title, max_score=Decimal(max_score), assessment_date=when,
            created_by=self.teacher,
        )
        for section, status in (section_statuses or {}).items():
            published = status == AssessmentSection.Status.PUBLISHED
            AssessmentSection.objects.create(
                assessment=assessment, section=section, status=status,
                published_by=self.teacher if published else None,
                published_at=timezone.now() if published else None,
            )
        return assessment

    def create_score(self, assessment, enrollment, score, recorded_section=None):
        return StudentScore.objects.create(
            assessment=assessment, enrollment=enrollment,
            recorded_section=recorded_section or enrollment.section,
            score=score, updated_by=self.teacher,
        )

    def url(self, child=None):
        return f"/api/v1/mobile/children/{(child or self.child).id}/grades/"

    def authenticate(self, *, user=None, client="mobile"):
        user = user or self.guardian
        refresh = RefreshToken.for_user(user)
        refresh["client"] = client
        refresh["token_version"] = user.token_version
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        return str(refresh.access_token)

    def test_published_assessments_are_grouped_with_totals_and_all_terms(self):
        first = self.create_assessment(
            title="مذاكرة", max_score="20.00",
            section_statuses={self.section_a: AssessmentSection.Status.PUBLISHED},
        )
        second = self.create_assessment(
            title="نهائي", max_score="40.00", when=date(2027, 1, 10),
            section_statuses={self.section_a: AssessmentSection.Status.PUBLISHED},
        )
        science = self.create_assessment(
            title="علوم", plan=self.science_plan, max_score="40.00",
            section_statuses={self.section_a: AssessmentSection.Status.PUBLISHED},
        )
        self.create_score(first, self.enrollment, Decimal("18.00"))
        self.create_score(second, self.enrollment, Decimal("38.00"))
        self.create_score(science, self.enrollment, Decimal("35.00"))
        self.authenticate()

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], "MOBILE_CHILD_GRADES_RETRIEVED")
        self.assertEqual([term["number"] for term in response.data["data"]["terms"]], [1, 2])
        term_one = response.data["data"]["terms"][0]
        self.assertEqual(len(term_one["subjects"]), 2)
        math = next(x for x in term_one["subjects"] if x["subject"]["id"] == str(self.math.id))
        self.assertEqual([x["id"] for x in math["assessments"]], [str(first.id), str(second.id)])
        self.assertEqual(math["total_score"], "56.00")
        self.assertEqual(math["total_max_score"], "60.00")
        self.assertEqual(math["percentage"], "93.33")
        self.assertTrue(math["is_complete"])
        self.assertEqual(response.data["data"]["terms"][1]["subjects"], [])

    def test_null_score_remains_visible_and_is_not_treated_as_zero(self):
        scored = self.create_assessment(
            title="مصحح", max_score="20.00",
            section_statuses={self.section_a: AssessmentSection.Status.PUBLISHED},
        )
        pending = self.create_assessment(
            title="بانتظار التصحيح", max_score="30.00", when=date(2026, 10, 11),
            section_statuses={self.section_a: AssessmentSection.Status.PUBLISHED},
        )
        self.create_score(scored, self.enrollment, Decimal("18.00"))
        self.create_score(pending, self.enrollment, None)
        self.authenticate()

        subject = self.client.get(self.url()).data["data"]["terms"][0]["subjects"][0]

        self.assertEqual(len(subject["assessments"]), 2)
        self.assertIsNone(next(x for x in subject["assessments"] if x["id"] == str(pending.id))["score"])
        self.assertEqual(subject["total_score"], "18.00")
        self.assertEqual(subject["total_max_score"], "50.00")
        self.assertFalse(subject["is_complete"])
        self.assertIsNone(subject["percentage"])

    def test_draft_for_student_section_is_hidden_and_excluded_from_totals(self):
        visible = self.create_assessment(
            title="منشور", max_score="20.00",
            section_statuses={self.section_a: AssessmentSection.Status.PUBLISHED},
        )
        draft = self.create_assessment(
            title="مسودة", max_score="100.00", when=date(2026, 10, 11),
            section_statuses={self.section_a: AssessmentSection.Status.DRAFT},
        )
        self.create_score(visible, self.enrollment, Decimal("15.00"))
        self.create_score(draft, self.enrollment, Decimal("100.00"))
        self.authenticate()

        subject = self.client.get(self.url()).data["data"]["terms"][0]["subjects"][0]

        self.assertEqual([x["title"] for x in subject["assessments"]], ["منشور"])
        self.assertEqual(subject["total_score"], "15.00")
        self.assertEqual(subject["total_max_score"], "20.00")

    def test_publication_status_is_bound_to_the_students_correct_section(self):
        child_b, enrollment_b = self.create_child(
            guardian=self.guardian, first_name="طالب ب", section=self.section_b
        )
        hidden = self.create_assessment(
            title="منشور لأ فقط", max_score="100.00",
            section_statuses={
                self.section_a: AssessmentSection.Status.PUBLISHED,
                self.section_b: AssessmentSection.Status.DRAFT,
            },
        )
        visible = self.create_assessment(
            title="منشور لب", max_score="20.00", when=date(2026, 10, 11),
            section_statuses={
                self.section_a: AssessmentSection.Status.DRAFT,
                self.section_b: AssessmentSection.Status.PUBLISHED,
            },
        )
        self.create_score(hidden, enrollment_b, Decimal("90.00"), self.section_b)
        self.create_score(visible, enrollment_b, Decimal("18.00"), self.section_b)
        self.authenticate()

        subjects = self.client.get(self.url(child_b)).data["data"]["terms"][0]["subjects"]
        assessments = [item for subject in subjects for item in subject["assessments"]]
        subject = subjects[0]

        self.assertEqual([x["title"] for x in assessments], ["منشور لب"])
        self.assertEqual(subject["total_score"], "18.00")
        self.assertEqual(subject["total_max_score"], "20.00")
        self.assertEqual(subject["percentage"], "90.00")
        self.assertTrue(subject["is_complete"])

    def test_transfer_history_uses_old_then_new_section(self):
        before = self.create_assessment(
            title="قبل النقل", when=date(2026, 10, 10),
            section_statuses={
                self.section_a: AssessmentSection.Status.PUBLISHED,
                self.section_b: AssessmentSection.Status.DRAFT,
            },
        )
        after = self.create_assessment(
            title="بعد النقل", when=date(2026, 11, 10),
            section_statuses={
                self.section_a: AssessmentSection.Status.DRAFT,
                self.section_b: AssessmentSection.Status.PUBLISHED,
            },
        )
        self.enrollment.section = self.section_b
        self.enrollment.save(update_fields=["section"])
        log = StudentAuditLog.objects.create(
            event_type=StudentAuditLog.EventType.SECTION_TRANSFER,
            actor=self.teacher, enrollment=self.enrollment,
            old_section=self.section_a, new_section=self.section_b,
        )
        StudentAuditLog.objects.filter(pk=log.pk).update(
            created_at=timezone.make_aware(datetime(2026, 11, 1, 9, 0))
        )
        self.authenticate()

        subjects = self.client.get(self.url()).data["data"]["terms"][0]["subjects"]
        ids = {item["id"] for subject in subjects for item in subject["assessments"]}

        self.assertEqual(ids, {str(before.id), str(after.id)})

    def test_recorded_section_controls_published_status_after_transfer(self):
        assessment = self.create_assessment(
            title="علامة تاريخية", when=date(2026, 11, 10),
            section_statuses={
                self.section_a: AssessmentSection.Status.PUBLISHED,
                self.section_b: AssessmentSection.Status.DRAFT,
            },
        )
        self.create_score(assessment, self.enrollment, Decimal("17.00"), self.section_a)
        self.enrollment.section = self.section_b
        self.enrollment.save(update_fields=["section"])
        self.authenticate()

        subjects = self.client.get(self.url()).data["data"]["terms"][0]["subjects"]
        ids = {item["id"] for subject in subjects for item in subject["assessments"]}

        self.assertIn(str(assessment.id), ids)

    def test_no_published_assessments_keeps_terms_with_empty_subjects(self):
        self.create_assessment(
            title="مسودة فقط",
            section_statuses={self.section_a: AssessmentSection.Status.DRAFT},
        )
        self.authenticate()

        terms = self.client.get(self.url()).data["data"]["terms"]

        self.assertEqual(len(terms), 2)
        self.assertTrue(all(term["subjects"] == [] for term in terms))

    def test_no_current_enrollment_returns_successful_empty_contract(self):
        self.authenticate()
        response = self.client.get(self.url(self.no_enrollment_child))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"], {
            "student": {
                "id": str(self.no_enrollment_child.id),
                "full_name": self.no_enrollment_child.full_name,
            },
            "academic_year": None,
            "terms": [],
        })

    def test_term_filter_and_validation(self):
        self.authenticate()
        response = self.client.get(self.url(), {"term": str(self.term_two.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([x["id"] for x in response.data["data"]["terms"]], [str(self.term_two.id)])
        self.assertEqual(self.client.get(self.url(), {"term": "invalid"}).status_code, 400)
        self.assertEqual(self.client.get(
            self.url(), {"term": "00000000-0000-0000-0000-000000000000"}
        ).status_code, 400)
        wrong_year = self.client.get(self.url(), {"term": str(self.old_term.id)})
        self.assertEqual(wrong_year.status_code, 400)
        self.assertIn("لا يتبع السنة الدراسية الحالية", wrong_year.data["errors"]["term"][0])

    def test_ownership_authentication_permissions_and_stale_tokens(self):
        self.authenticate()
        self.assertEqual(self.client.get(self.url(self.other_child)).status_code, 404)
        self.client.credentials()
        self.assertEqual(self.client.get(self.url()).status_code, 401)
        self.authenticate(client="web")
        self.assertEqual(self.client.get(self.url()).status_code, 401)
        self.authenticate(user=self.teacher)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.guardian.must_change_password = True
        self.guardian.save(update_fields=["must_change_password"])
        self.authenticate()
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "PASSWORD_CHANGE_REQUIRED")
        self.guardian.must_change_password = False
        self.guardian.save(update_fields=["must_change_password"])
        stale = self.authenticate()
        self.guardian.token_version += 1
        self.guardian.save(update_fields=["token_version"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {stale}")
        self.assertEqual(self.client.get(self.url()).status_code, 401)

    def test_inactive_guardian_is_rejected(self):
        access = self.authenticate()
        self.guardian.is_active = False
        self.guardian.save(update_fields=["is_active"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(self.client.get(self.url()).status_code, 401)

    def test_response_is_minimal_and_methods_are_get_only(self):
        assessment = self.create_assessment(
            title="منشور",
            section_statuses={self.section_a: AssessmentSection.Status.PUBLISHED},
        )
        self.create_score(assessment, self.enrollment, Decimal("18.00"))
        self.authenticate()
        response = self.client.get(self.url())
        data = response.data["data"]
        self.assertEqual(set(data), {"student", "academic_year", "terms"})
        assessment_data = data["terms"][0]["subjects"][0]["assessments"][0]
        self.assertEqual(set(assessment_data), {
            "id", "title", "assessment_date", "score", "max_score",
        })
        forbidden = {
            "published_by", "published_at", "created_by", "created_by_username",
            "updated_by", "updated_by_username", "score_audit_logs",
            "student_audit_logs",
        }
        self.assertTrue(forbidden.isdisjoint(collect_dictionary_keys(response.data)))
        for method in (
            self.client.post, self.client.put, self.client.patch, self.client.delete,
        ):
            method_response = method(self.url(), {}, format="json")
            self.assertEqual(method_response.status_code, 405)
            self.assertEqual(method_response.data["code"], "METHOD_NOT_ALLOWED")

    def test_query_count_does_not_grow_with_more_assessments(self):
        first = self.create_assessment(
            title="واحد",
            section_statuses={self.section_a: AssessmentSection.Status.PUBLISHED},
        )
        self.create_score(first, self.enrollment, Decimal("10.00"))
        self.authenticate()
        with CaptureQueriesContext(connection) as initial_queries:
            self.client.get(self.url())

        expanded_assessments = (
            ("رياضيات إضافية", self.math_plan, date(2026, 10, 11)),
            ("علوم واحد", self.science_plan, date(2026, 10, 12)),
            ("علوم اثنان", self.science_plan, date(2026, 10, 13)),
        )
        for title, plan, assessment_date in expanded_assessments:
            assessment = self.create_assessment(
                title=title, plan=plan, when=assessment_date,
                section_statuses={self.section_a: AssessmentSection.Status.PUBLISHED},
            )
            self.create_score(assessment, self.enrollment, Decimal("10.00"))

        with CaptureQueriesContext(connection) as expanded_queries:
            self.client.get(self.url())

        self.assertEqual(len(expanded_queries), len(initial_queries))
