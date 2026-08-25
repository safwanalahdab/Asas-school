from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib import admin
from django.test import TestCase
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, GradeSubject, Section, Subject, Term
from students.models import Enrollment, Student, StudentAuditLog
from students.services import transfer_student_between_sections
from teaching.models import TeacherAssignment

from .models import Assessment, AssessmentSection, ScoreAuditLog, StudentScore
from .admin import StudentScoreAdmin
from .selectors import get_assessment_score_rows, get_student_term_results
from .services import (
    create_assessment, create_assessments_for_grade, delete_assessment,
    publish_section_assessments, save_assessment_scores_bulk, update_assessment,
)

User = get_user_model()


class GradesRefactorTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="grades-admin", password="Strong!123", role=User.Role.SCHOOL_ADMIN, must_change_password=False)
        self.teacher = User.objects.create_user(username="grades-teacher", password="Strong!123", role=User.Role.TEACHER, must_change_password=False)
        self.year = AcademicYear.objects.create(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        self.term = Term.objects.create(academic_year=self.year, number=Term.Number.FIRST, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        self.grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="الأول")
        self.a = Section.objects.create(academic_year=self.year, grade_level=self.grade, name="أ")
        self.b = Section.objects.create(academic_year=self.year, grade_level=self.grade, name="ب")
        self.subject = Subject.objects.create(name="الرياضيات")
        self.plan = GradeSubject.objects.create(academic_year=self.year, grade_level=self.grade, subject=self.subject)
        self.student = Student.objects.create(first_name="محمد", last_name="أحمد", birth_date=date(2018, 1, 1), gender=Student.Gender.MALE)
        self.enrollment = Enrollment.objects.create(student=self.student, academic_year=self.year, section=self.a, enrollment_date=date(2026, 1, 5))
        TeacherAssignment.objects.create(teacher=self.teacher, grade_subject=self.plan, section=self.a, start_date=date(2026, 1, 1))
        self.client = APIClient()
        self.client.force_authenticate(self.admin, token={"client": "web"})

    def assessment(self, section=None, when=date(2026, 2, 1)):
        return create_assessment(section=section or self.a, grade_subject=self.plan, term=self.term, title="مذاكرة 1", max_score=Decimal("20"), assessment_date=when, actor=self.admin)

    def test_single_and_grade_wide_creation(self):
        single = self.assessment()
        self.assertEqual(list(single.assessment_sections.values_list("section_id", flat=True)), [self.a.id])
        Assessment.objects.all().delete()
        shared = create_assessments_for_grade(grade_subject=self.plan, term=self.term, title="شفهي", max_score=Decimal("10"), assessment_date=date(2026, 2, 2), actor=self.admin)
        self.assertEqual(Assessment.objects.count(), 1)
        self.assertEqual(shared.assessment_sections.count(), 2)

    def test_scope_date_and_duplicate_validation(self):
        other_year = AcademicYear.objects.create(start_date=date(2027, 1, 1), end_date=date(2027, 12, 31))
        wrong = Section.objects.create(academic_year=other_year, grade_level=self.grade, name="أ")
        with self.assertRaises(ValidationError):
            create_assessment(section=wrong, grade_subject=self.plan, term=self.term, title="x", max_score=Decimal("10"), assessment_date=date(2026, 2, 1), actor=self.admin)
        self.assessment()
        with self.assertRaises(ValidationError):
            self.assessment()
        with self.assertRaises(ValidationError):
            create_assessment(section=self.a, grade_subject=self.plan, term=self.term, title="خارج الفصل", max_score=Decimal("10"), assessment_date=date(2027, 1, 1), actor=self.admin)

    def test_teacher_is_scoped_per_section(self):
        shared = create_assessments_for_grade(grade_subject=self.plan, term=self.term, title="مشترك", max_score=Decimal("20"), assessment_date=date(2026, 2, 1), actor=self.admin)
        save_assessment_scores_bulk(assessment=shared, section=self.a, records=[{"enrollment": self.enrollment, "score": Decimal("18")}], actor=self.teacher)
        self.enrollment.section = self.b
        self.enrollment.save(update_fields=["section"])
        with self.assertRaises(PermissionDenied):
            save_assessment_scores_bulk(assessment=shared, section=self.b, records=[{"enrollment": self.enrollment, "score": Decimal("19")}], actor=self.teacher)

    def test_bulk_null_zero_bounds_and_audit(self):
        assessment = self.assessment()
        save_assessment_scores_bulk(assessment=assessment, section=self.a, records=[{"enrollment": self.enrollment, "score": Decimal("0")}], actor=self.admin)
        score = StudentScore.objects.get()
        self.assertEqual(score.score, Decimal("0"))
        self.assertEqual(score.recorded_section, self.a)
        save_assessment_scores_bulk(assessment=assessment, section=self.a, records=[{"enrollment": self.enrollment, "score": None}], actor=self.admin)
        score.refresh_from_db()
        self.assertIsNone(score.score)
        self.assertEqual(ScoreAuditLog.objects.count(), 2)
        self.assertTrue(ScoreAuditLog.objects.filter(old_score=Decimal("0"), new_score__isnull=True).exists())
        with self.assertRaises(ValidationError):
            save_assessment_scores_bulk(assessment=assessment, section=self.a, records=[{"enrollment": self.enrollment, "score": Decimal("21")}], actor=self.admin)

    def test_late_enrollment_is_not_in_sheet(self):
        assessment = self.assessment(when=date(2026, 2, 1))
        late_student = Student.objects.create(first_name="متأخر", last_name="طالب", birth_date=date(2018, 2, 2), gender=Student.Gender.MALE)
        Enrollment.objects.create(student=late_student, academic_year=self.year, section=self.a, enrollment_date=date(2026, 3, 1))
        rows = get_assessment_score_rows(assessment=assessment, section=self.a)
        self.assertEqual([row["student"] for row in rows], [self.student.id])

    def test_transfer_preserves_one_historical_score_and_results(self):
        assessment = create_assessments_for_grade(grade_subject=self.plan, term=self.term, title="مشترك", max_score=Decimal("20"), assessment_date=date(2026, 2, 1), actor=self.admin)
        save_assessment_scores_bulk(assessment=assessment, section=self.a, records=[{"enrollment": self.enrollment, "score": Decimal("18")}], actor=self.admin)
        transfer_student_between_sections(enrollment=self.enrollment, target_section=self.b, actor=self.admin)
        self.enrollment.refresh_from_db()
        result = get_student_term_results(enrollment=self.enrollment, term=self.term)
        self.assertEqual(result[0]["assessments"][0]["score"], Decimal("18"))
        self.assertEqual(StudentScore.objects.count(), 1)
        self.assertEqual(StudentScore.objects.get().recorded_section, self.a)
        newer = create_assessment(section=self.b, grade_subject=self.plan, term=self.term, title="بعد النقل", max_score=Decimal("20"), assessment_date=timezone.localdate(), actor=self.admin)
        save_assessment_scores_bulk(assessment=newer, section=self.b, records=[{"enrollment": self.enrollment, "score": Decimal("19")}], actor=self.admin)
        self.assertEqual(StudentScore.objects.count(), 2)

    def test_publish_skips_future_and_allows_null(self):
        past = self.assessment()
        save_assessment_scores_bulk(assessment=past, section=self.a, records=[{"enrollment": self.enrollment, "score": None}], actor=self.admin)
        future_date = min(self.term.end_date, timezone.localdate() + timedelta(days=30))
        future = create_assessment(section=self.a, grade_subject=self.plan, term=self.term, title="مستقبلي", max_score=Decimal("20"), assessment_date=future_date, actor=self.admin)
        result = publish_section_assessments(section=self.a, term=self.term, actor=self.admin)
        past.assessment_sections.get().refresh_from_db()
        self.assertEqual(past.assessment_sections.get().status, AssessmentSection.Status.PUBLISHED)
        if future_date > timezone.localdate():
            self.assertEqual(future.assessment_sections.get().status, AssessmentSection.Status.DRAFT)
            self.assertEqual(result["skipped_future_count"], 1)

    def test_published_definition_and_deletion_rules(self):
        assessment = self.assessment()
        link = assessment.assessment_sections.get()
        link.status, link.published_by, link.published_at = AssessmentSection.Status.PUBLISHED, self.admin, timezone.now()
        link.save()
        with self.assertRaises(ValidationError):
            update_assessment(assessment=assessment, actor=self.admin, title="تعديل")
        with self.assertRaises(ValidationError):
            delete_assessment(assessment=assessment, actor=self.admin)
        draft = create_assessment(section=self.a, grade_subject=self.plan, term=self.term, title="قابل للحذف", max_score=Decimal("20"), assessment_date=date(2026, 4, 1), actor=self.admin)
        save_assessment_scores_bulk(assessment=draft, section=self.a, records=[{"enrollment": self.enrollment, "score": None}], actor=self.admin)
        with self.assertRaises(ValidationError):
            delete_assessment(assessment=draft, actor=self.admin)

    def test_api_grade_wide_and_section_context(self):
        response = self.client.post("/api/v1/grades/assessments/create-for-grade/", {
            "grade_subject": str(self.plan.id), "term": str(self.term.id),
            "title": "اختبار API", "max_score": "20.00", "assessment_date": "2026-02-01",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        assessment = Assessment.objects.get()
        self.assertEqual(len(response.data["data"]["sections"]), 2)
        missing = self.client.get(f"/api/v1/grades/assessments/{assessment.id}/scores/")
        self.assertEqual(missing.status_code, 400)
        bulk = self.client.post(f"/api/v1/grades/assessments/{assessment.id}/scores/bulk/", {
            "section": str(self.a.id),
            "records": [{"enrollment": str(self.enrollment.id), "score": "18.00"}],
        }, format="json")
        self.assertEqual(bulk.status_code, 200)
        self.assertEqual(StudentScore.objects.get().score, Decimal("18"))

    def test_forbidden_web_roles_and_superuser(self):
        for role in (User.Role.SECRETARIAT, User.Role.TECH_SUPPORT, User.Role.GUARDIAN):
            user = User.objects.create_user(username=f"role-{role}", password="Strong!123", role=role, must_change_password=False)
            self.client.force_authenticate(user, token={"client": "web"})
            self.assertEqual(self.client.get("/api/v1/grades/assessments/").status_code, 403)
        superuser = User.objects.create_superuser(username="root-grades", password="Strong!123")
        self.client.force_authenticate(superuser, token={"client": "web"})
        self.assertEqual(self.client.get("/api/v1/grades/assessments/").status_code, 200)

    def test_transfer_history_controls_score_sheet_membership(self):
        self.enrollment.enrollment_date = date(2026, 9, 1)
        self.enrollment.save(update_fields=["enrollment_date"])
        old_assessment = create_assessments_for_grade(
            grade_subject=self.plan, term=self.term, title="علامة تاريخية",
            max_score=Decimal("20"), assessment_date=date(2026, 10, 5), actor=self.admin,
        )
        save_assessment_scores_bulk(
            assessment=old_assessment, section=self.a,
            records=[{"enrollment": self.enrollment, "score": Decimal("18")}],
            actor=self.admin,
        )
        before_transfer = create_assessment(
            section=self.b, grade_subject=self.plan, term=self.term,
            title="قبل النقل", max_score=Decimal("20"),
            assessment_date=date(2026, 10, 10), actor=self.admin,
        )
        after_transfer = create_assessment(
            section=self.b, grade_subject=self.plan, term=self.term,
            title="بعد النقل", max_score=Decimal("20"),
            assessment_date=date(2026, 11, 10), actor=self.admin,
        )
        transfer_student_between_sections(
            enrollment=self.enrollment, target_section=self.b, actor=self.admin,
        )
        transfer_at = timezone.make_aware(datetime(2026, 11, 1, 9, 0))
        StudentAuditLog.objects.filter(enrollment=self.enrollment).update(created_at=transfer_at)
        self.enrollment.refresh_from_db()

        self.assertEqual(
            get_assessment_score_rows(assessment=before_transfer, section=self.b),
            [],
        )
        self.assertEqual(
            [row["enrollment"] for row in get_assessment_score_rows(
                assessment=after_transfer, section=self.b,
            )],
            [self.enrollment.id],
        )
        results = get_student_term_results(enrollment=self.enrollment, term=self.term)
        result_by_title = {
            item["title"]: item["score"]
            for subject in results
            for item in subject["assessments"]
        }
        self.assertEqual(result_by_title["علامة تاريخية"], Decimal("18"))
        self.assertNotIn("قبل النقل", result_by_title)
        self.assertIn("بعد النقل", result_by_title)

    def test_admin_score_change_creates_admin_audit_log(self):
        assessment = self.assessment()
        save_assessment_scores_bulk(
            assessment=assessment, section=self.a,
            records=[{"enrollment": self.enrollment, "score": Decimal("12")}],
            actor=self.admin,
        )
        score = StudentScore.objects.get()
        score.score = Decimal("17")
        request = RequestFactory().post("/admin/grades/studentscore/")
        request.user = self.teacher
        StudentScoreAdmin(StudentScore, admin.site).save_model(
            request, score, form=None, change=True,
        )
        self.assertTrue(ScoreAuditLog.objects.filter(
            assessment=assessment,
            enrollment=self.enrollment,
            old_score=Decimal("12"),
            new_score=Decimal("17"),
            actor=self.teacher,
            source=ScoreAuditLog.Source.ADMIN,
        ).exists())
        self.assertTrue(ScoreAuditLog.objects.filter(
            source=ScoreAuditLog.Source.API,
        ).exists())
