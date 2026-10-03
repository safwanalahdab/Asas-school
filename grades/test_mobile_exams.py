from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

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


def all_keys(value):
    keys = set()
    if isinstance(value, dict):
        keys.update(value)
        for item in value.values():
            keys.update(all_keys(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            keys.update(all_keys(item))
    return keys


class MobileExamsApiTests(TestCase):
    today = date(2026, 10, 3)

    def setUp(self):
        self.client = APIClient()
        self.guardian = self.make_user("exam-guardian", User.Role.GUARDIAN)
        self.other_guardian = self.make_user("other-exam-guardian", User.Role.GUARDIAN)
        self.teacher = self.make_user("exam-teacher", User.Role.TEACHER)
        self.year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1), end_date=date(2027, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )
        self.term_one = Term.objects.create(
            academic_year=self.year, number=Term.Number.FIRST,
            start_date=date(2026, 9, 1), end_date=date(2027, 1, 15),
        )
        self.term_two = Term.objects.create(
            academic_year=self.year, number=Term.Number.SECOND,
            start_date=date(2027, 1, 16), end_date=date(2027, 6, 30),
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
        self.math = Subject.objects.create(name="الرياضيات")
        self.science = Subject.objects.create(name="العلوم")
        self.math_plan = GradeSubject.objects.create(
            academic_year=self.year, grade_level=self.grade, subject=self.math
        )
        self.science_plan = GradeSubject.objects.create(
            academic_year=self.year, grade_level=self.grade, subject=self.science
        )
        self.child, self.enrollment, self.link = self.make_child(
            self.guardian, "أحمد", self.section_a
        )
        self.other_child, _, _ = self.make_child(
            self.other_guardian, "غريب", self.section_a
        )
        self.no_enrollment_child, _, _ = self.make_child(
            self.guardian, "بلا تسجيل", None
        )

    def make_user(self, username, role):
        return User.objects.create_user(
            username=username, password="StrongPass!493", role=role,
            must_change_password=False,
        )

    def make_child(self, guardian, first_name, section):
        student = Student.objects.create(
            first_name=first_name, last_name="محمد", birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )
        link = GuardianStudent.objects.create(guardian=guardian, student=student)
        enrollment = None
        if section is not None:
            enrollment = Enrollment.objects.create(
                student=student, academic_year=section.academic_year,
                section=section, enrollment_date=section.academic_year.start_date,
            )
        return student, enrollment, link

    def make_exam(
        self, title, when, *, section=None, plan=None, term=None,
        schedule_status=AssessmentSection.ScheduleStatus.PUBLISHED,
        result_status=AssessmentSection.Status.DRAFT,
    ):
        assessment = Assessment.objects.create(
            grade_subject=plan or self.math_plan,
            term=term or self.term_one,
            title=title,
            max_score=Decimal("20.00"),
            assessment_date=when,
            created_by=self.teacher,
        )
        schedule_published = schedule_status == AssessmentSection.ScheduleStatus.PUBLISHED
        result_published = result_status == AssessmentSection.Status.PUBLISHED
        link = AssessmentSection.objects.create(
            assessment=assessment,
            section=section or self.section_a,
            schedule_status=schedule_status,
            schedule_published_by=self.teacher if schedule_published else None,
            schedule_published_at=timezone.now() if schedule_published else None,
            status=result_status,
            published_by=self.teacher if result_published else None,
            published_at=timezone.now() if result_published else None,
        )
        return assessment, link

    def authenticate(self, user=None, client="mobile"):
        user = user or self.guardian
        refresh = RefreshToken.for_user(user)
        refresh["client"] = client
        refresh["token_version"] = user.token_version
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        return str(refresh.access_token)

    def url(self, child=None):
        return f"/api/v1/mobile/children/{(child or self.child).id}/exams/"

    def get(self, params=None, child=None):
        with patch("grades.mobile_selectors.timezone.localdate", return_value=self.today):
            return self.client.get(self.url(child), params or {})

    def test_authentication_permissions_and_ownership(self):
        self.assertEqual(self.get().status_code, 401)
        self.authenticate(client="web")
        self.assertEqual(self.get().status_code, 401)
        self.authenticate(self.teacher)
        self.assertEqual(self.get().status_code, 403)
        self.authenticate()
        self.assertEqual(self.get(child=self.other_child).status_code, 404)

        self.link.is_active = False
        self.link.save(update_fields=["is_active"])
        self.assertEqual(self.get().status_code, 404)
        self.link.is_active = True
        self.link.save(update_fields=["is_active"])
        self.child.is_active = False
        self.child.save(update_fields=["is_active"])
        self.assertEqual(self.get().status_code, 404)

    def test_password_gate_and_stale_or_inactive_account(self):
        self.guardian.must_change_password = True
        self.guardian.save(update_fields=["must_change_password"])
        self.authenticate()
        response = self.get()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "PASSWORD_CHANGE_REQUIRED")

        self.guardian.must_change_password = False
        self.guardian.save(update_fields=["must_change_password"])
        token = self.authenticate()
        self.guardian.token_version += 1
        self.guardian.save(update_fields=["token_version"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(self.get().status_code, 401)

        token = self.authenticate()
        self.guardian.is_active = False
        self.guardian.save(update_fields=["is_active"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(self.get().status_code, 401)

    def test_empty_contract_without_enrollment_or_active_year(self):
        self.authenticate()
        response = self.get(child=self.no_enrollment_child)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["data"]["academic_year"])
        self.assertEqual(response.data["data"]["exams"], [])
        self.assertEqual(response.data["meta"]["pagination"]["count"], 0)
        self.assertEqual(response.data["meta"]["pagination"]["page_size"], 20)

        self.year.status = AcademicYear.Status.CLOSED
        self.year.save(update_fields=["status"])
        response = self.get()
        self.assertIsNone(response.data["data"]["academic_year"])
        self.assertEqual(response.data["data"]["exams"], [])

    def test_schedule_publication_is_independent_from_results_and_scores(self):
        draft, _ = self.make_exam(
            "موعد مسودة", date(2026, 10, 4),
            schedule_status=AssessmentSection.ScheduleStatus.DRAFT,
        )
        visible, _ = self.make_exam("موعد منشور", date(2026, 10, 5))
        published_result, _ = self.make_exam(
            "نتيجة منشورة", date(2026, 10, 6),
            result_status=AssessmentSection.Status.PUBLISHED,
        )
        StudentScore.objects.create(
            assessment=published_result, enrollment=self.enrollment,
            recorded_section=self.section_a, score=Decimal("18.00"),
            updated_by=self.teacher,
        )
        self.authenticate()
        response = self.get()
        ids = {item["id"] for item in response.data["data"]["exams"]}
        self.assertNotIn(str(draft.id), ids)
        self.assertEqual(ids, {str(visible.id), str(published_result.id)})

        AssessmentSection.objects.filter(assessment=visible).update(
            schedule_status=AssessmentSection.ScheduleStatus.DRAFT,
            schedule_published_by=None, schedule_published_at=None,
        )
        ids = {item["id"] for item in self.get().data["data"]["exams"]}
        self.assertNotIn(str(visible.id), ids)

    def test_other_section_is_hidden(self):
        self.make_exam("شعبة أخرى", date(2026, 10, 4), section=self.section_b)
        self.authenticate()
        self.assertEqual(self.get().data["data"]["exams"], [])

    def test_transfer_history_and_same_day_use_expected_section(self):
        before, _ = self.make_exam("قبل النقل", date(2026, 10, 1), section=self.section_a)
        after, _ = self.make_exam("بعد النقل", date(2026, 10, 5), section=self.section_b)
        same_day, _ = self.make_exam("يوم النقل", date(2026, 10, 3), section=self.section_b)
        old_future, _ = self.make_exam("قديم قادم", date(2026, 10, 6), section=self.section_a)
        self.enrollment.section = self.section_b
        self.enrollment.save(update_fields=["section"])
        log = StudentAuditLog.objects.create(
            event_type=StudentAuditLog.EventType.SECTION_TRANSFER,
            actor=self.teacher, enrollment=self.enrollment,
            old_section=self.section_a, new_section=self.section_b,
        )
        StudentAuditLog.objects.filter(pk=log.pk).update(
            created_at=timezone.make_aware(datetime(2026, 10, 3, 9, 0))
        )
        self.authenticate()
        response = self.get({"view": "all"})
        ids = {item["id"] for item in response.data["data"]["exams"]}
        self.assertEqual(ids, {str(before.id), str(after.id), str(same_day.id)})
        self.assertNotIn(str(old_future.id), ids)
        same_day_data = next(
            item for item in response.data["data"]["exams"]
            if item["id"] == str(same_day.id)
        )
        self.assertEqual(same_day_data["section"]["id"], str(self.section_b.id))

    def test_views_dates_filters_and_ordering(self):
        past_old, _ = self.make_exam("قديم", date(2026, 9, 20))
        past_new, _ = self.make_exam("أحدث", date(2026, 10, 2))
        today, _ = self.make_exam("اليوم", self.today)
        next_b, _ = self.make_exam("باء", date(2026, 10, 5))
        next_a, _ = self.make_exam("ألف", date(2026, 10, 5))
        self.authenticate()

        default_ids = [item["id"] for item in self.get().data["data"]["exams"]]
        self.assertEqual(default_ids, [str(today.id), str(next_a.id), str(next_b.id)])
        past_ids = [
            item["id"] for item in self.get({"view": "past"}).data["data"]["exams"]
        ]
        self.assertEqual(past_ids, [str(past_new.id), str(past_old.id)])
        all_ids = [
            item["id"] for item in self.get({"view": "all"}).data["data"]["exams"]
        ]
        self.assertEqual(
            all_ids,
            [str(today.id), str(next_a.id), str(next_b.id), str(past_new.id), str(past_old.id)],
        )
        bounded = self.get({
            "view": "all", "date_from": "2026-10-02", "date_to": "2026-10-03",
        })
        self.assertEqual(
            {item["id"] for item in bounded.data["data"]["exams"]},
            {str(past_new.id), str(today.id)},
        )

        with patch(
            "grades.mobile_selectors.timezone.localdate",
            return_value=date(2026, 10, 4),
        ):
            moved = self.client.get(self.url(), {"view": "past"})
        self.assertIn(
            str(today.id),
            {item["id"] for item in moved.data["data"]["exams"]},
        )

    def test_invalid_filters_and_unknown_valid_uuids(self):
        self.authenticate()
        for params in (
            {"view": "invalid"}, {"term": "invalid"}, {"subject": "invalid"},
            {"date_from": "2026-10-05", "date_to": "2026-10-04"},
            {"page": 0}, {"page_size": 0}, {"page_size": 101},
        ):
            self.assertEqual(self.get(params).status_code, 400)
        for field in ("term", "subject"):
            response = self.get({field: str(uuid4())})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["data"]["exams"], [])

    def test_term_and_subject_filters(self):
        math, _ = self.make_exam("رياضيات", date(2026, 10, 4))
        science, _ = self.make_exam(
            "علوم", date(2026, 10, 5), plan=self.science_plan
        )
        later, _ = self.make_exam(
            "فصل ثان", date(2027, 2, 1), term=self.term_two
        )
        self.authenticate()
        self.assertEqual(
            [item["id"] for item in self.get({"subject": str(self.science.id)}).data["data"]["exams"]],
            [str(science.id)],
        )
        self.assertEqual(
            [item["id"] for item in self.get({"term": str(self.term_two.id)}).data["data"]["exams"]],
            [str(later.id)],
        )
        self.assertNotEqual(math.id, science.id)

    def test_response_is_minimal_and_methods_are_read_only(self):
        self.make_exam("اختبار", date(2026, 10, 4))
        self.authenticate()
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], "MOBILE_CHILD_EXAMS_RETRIEVED")
        self.assertEqual(set(response.data["data"]), {"student", "academic_year", "exams"})
        self.assertEqual(set(response.data["data"]["exams"][0]), {
            "id", "title", "subject", "assessment_date", "temporal_status",
            "term", "section", "max_score",
        })
        forbidden = {
            "score", "status", "schedule_status", "schedule_published_by",
            "schedule_published_at", "published_by", "published_at", "created_by",
            "created_at", "updated_at", "audit_logs",
        }
        self.assertTrue(forbidden.isdisjoint(all_keys(response.data)))
        for method in (self.client.post, self.client.put, self.client.patch, self.client.delete):
            result = method(self.url(), {}, format="json")
            self.assertEqual(result.status_code, 405)
            self.assertEqual(result.data["code"], "METHOD_NOT_ALLOWED")

    def test_pagination_is_final_stable_and_merged_with_role(self):
        exams = [
            self.make_exam(f"امتحان {number:02}", date(2026, 10, 4))[0]
            for number in range(5)
        ]
        self.authenticate()
        first = self.get({"page": 1, "page_size": 2})
        second = self.get({"page": 2, "page_size": 2})
        first_ids = [item["id"] for item in first.data["data"]["exams"]]
        second_ids = [item["id"] for item in second.data["data"]["exams"]]
        self.assertTrue(set(first_ids).isdisjoint(second_ids))
        self.assertEqual(first.data["meta"]["pagination"]["count"], len(exams))
        self.assertEqual(first.data["meta"]["pagination"]["total_pages"], 3)
        self.assertEqual(first.data["meta"]["pagination"]["page_size"], 2)
        self.assertEqual(first.data["meta"]["requester_role"]["code"], User.Role.GUARDIAN)
        self.assertEqual(first_ids, [
            item["id"] for item in self.get({"page": 1, "page_size": 2}).data["data"]["exams"]
        ])
        maximum = self.get({"page_size": 100})
        self.assertEqual(maximum.status_code, 200)
        self.assertEqual(maximum.data["meta"]["pagination"]["page_size"], 100)

    def test_pagination_count_is_after_historical_matching(self):
        visible, _ = self.make_exam("ظاهر", date(2026, 10, 4), section=self.section_a)
        self.make_exam("مرشح غير مطابق", date(2026, 10, 4), section=self.section_b)
        self.authenticate()
        response = self.get({"page_size": 1})
        self.assertEqual(response.data["meta"]["pagination"]["count"], 1)
        self.assertEqual(response.data["data"]["exams"][0]["id"], str(visible.id))

    def test_query_count_does_not_grow_with_more_exams(self):
        self.make_exam("واحد", date(2026, 10, 4))
        self.authenticate()
        with patch("grades.mobile_selectors.timezone.localdate", return_value=self.today):
            with CaptureQueriesContext(connection) as initial:
                self.client.get(self.url())
        for number in range(4):
            self.make_exam(f"إضافي {number}", date(2026, 10, 5 + number))
        with patch("grades.mobile_selectors.timezone.localdate", return_value=self.today):
            with CaptureQueriesContext(connection) as expanded:
                self.client.get(self.url())
        self.assertEqual(len(expanded), len(initial))
