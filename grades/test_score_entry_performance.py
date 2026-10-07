import uuid
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.db.models import Prefetch, Q
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import serializers
from rest_framework.test import APIClient

from academics.models import (
    AcademicYear, GradeLevel, GradeSubject, Section, Subject, SupervisorScope,
    SupervisorScopeStage, Term,
)
from students.models import Enrollment, Student, StudentAuditLog
from teaching.models import TeacherAssignment

from .models import ScoreAuditLog, StudentScore
from .selectors import get_assessment_score_rows, get_enrollment_section_id_on_date
from .serializers import BulkAssessmentScoresSerializer
from .services import create_assessments_for_grade


User = get_user_model()

ASSESSMENT_DATE = date(2026, 6, 1)
SCOPE_TABLE = 'FROM "academics_supervisor_scope"'


def legacy_score_rows(*, assessment, section):
    """Verbatim copy of get_assessment_score_rows before candidate narrowing."""
    scores = StudentScore.objects.filter(assessment=assessment, recorded_section=section).select_related("updated_by")
    scored_ids = scores.values_list("enrollment_id", flat=True)
    transfer_history = StudentAuditLog.objects.filter(
        event_type=StudentAuditLog.EventType.SECTION_TRANSFER,
    ).order_by("created_at", "id")
    enrollments = Enrollment.objects.filter(
        Q(academic_year=section.academic_year, enrollment_date__lte=assessment.assessment_date)
        | Q(id__in=scored_ids)
    ).select_related("student").prefetch_related(
        Prefetch("assessment_scores", queryset=scores, to_attr="selected_scores"),
        Prefetch("audit_logs", queryset=transfer_history, to_attr="section_transfer_history"),
    ).distinct().order_by("student__first_name", "student__last_name")
    rows = []
    for enrollment in enrollments:
        item = enrollment.selected_scores[0] if enrollment.selected_scores else None
        if item is None and get_enrollment_section_id_on_date(
            enrollment=enrollment,
            target_date=assessment.assessment_date,
            transfer_logs=enrollment.section_transfer_history,
        ) != section.id:
            continue
        rows.append({
            "enrollment": enrollment.id, "student": enrollment.student_id,
            "student_display": enrollment.student.full_name,
            "score": item.score if item else None,
            "updated_by": item.updated_by_id if item else None,
            "updated_by_username": item.updated_by.username if item else None,
            "updated_at": item.updated_at if item else None,
        })
    return rows


class LegacyScoreRecordSerializer(serializers.Serializer):
    enrollment = serializers.PrimaryKeyRelatedField(queryset=Enrollment.objects.all())
    score = serializers.DecimalField(
        max_digits=7, decimal_places=2, min_value=Decimal("0"), required=True, allow_null=True,
    )


class LegacyBulkScoresSerializer(serializers.Serializer):
    """The pre-change request contract, used to prove errors are unchanged."""
    section = serializers.PrimaryKeyRelatedField(queryset=Section.objects.all())
    records = LegacyScoreRecordSerializer(many=True, allow_empty=False)


class ScoreEntryTestBase(TestCase):
    def setUp(self):
        self.admin = self.user("perf-admin", User.Role.SCHOOL_ADMIN)
        self.teacher = self.user("perf-teacher", User.Role.TEACHER)
        self.supervisor = self.user("perf-supervisor", User.Role.SUPERVISOR)
        scope = SupervisorScope.objects.create(
            supervisor=self.supervisor, scope_type=SupervisorScope.ScopeType.SELECTED_STAGES,
        )
        SupervisorScopeStage.objects.create(scope=scope, stage=GradeLevel.Stage.PRIMARY)

        self.year = AcademicYear.objects.create(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        self.term = Term.objects.create(
            academic_year=self.year, number=Term.Number.FIRST,
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        )
        self.grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="Perf primary")
        self.a = Section.objects.create(academic_year=self.year, grade_level=self.grade, name="A")
        self.b = Section.objects.create(academic_year=self.year, grade_level=self.grade, name="B")
        self.c = Section.objects.create(academic_year=self.year, grade_level=self.grade, name="C")
        self.plan = GradeSubject.objects.create(
            academic_year=self.year, grade_level=self.grade, subject=Subject.objects.create(name="Perf math"),
        )
        TeacherAssignment.objects.create(
            teacher=self.teacher, grade_subject=self.plan, section=self.a, start_date=date(2026, 1, 1),
        )
        self.client = APIClient()
        self.student_counter = 0

    def user(self, username, role):
        user = User.objects.create_user(username=username, password="x", role=role, must_change_password=False)
        user.user_permissions.add(*Permission.objects.filter(content_type__app_label="grades"))
        return user

    def new_assessment(self, title):
        return create_assessments_for_grade(
            grade_subject=self.plan, term=self.term, title=title,
            max_score=Decimal("20"), assessment_date=ASSESSMENT_DATE, actor=self.admin,
        )

    def enroll(self, section, *, name=None, enrollment_date=date(2026, 1, 5), year=None):
        self.student_counter += 1
        student = Student.objects.create(
            first_name=name or f"Student{self.student_counter:03d}", last_name="Perf",
            birth_date=date(2018, 1, 1), gender=Student.Gender.MALE,
        )
        return Enrollment.objects.create(
            student=student, academic_year=year or self.year, section=section,
            enrollment_date=enrollment_date,
        )

    def transfer(self, enrollment, old_section, new_section, when):
        log = StudentAuditLog.objects.create(
            event_type=StudentAuditLog.EventType.SECTION_TRANSFER, actor=self.admin,
            enrollment=enrollment, old_section=old_section, new_section=new_section,
        )
        StudentAuditLog.objects.filter(pk=log.pk).update(
            created_at=timezone.make_aware(datetime(when.year, when.month, when.day, 9, 0)),
        )
        enrollment.section = new_section
        enrollment.save(update_fields=["section"])

    def bulk_url(self, assessment):
        return f"/api/v1/grades/assessments/{assessment.id}/scores/bulk/"

    def post_bulk(self, user, assessment, section, records):
        self.client.force_authenticate(user, token={"client": "web"})
        payload = {
            "section": str(section.id),
            "records": [
                {"enrollment": str(getattr(enrollment, "id", enrollment)), "score": score}
                for enrollment, score in records
            ],
        }
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.post(self.bulk_url(assessment), payload, format="json")
        return response, ctx.captured_queries


class ScoreSheetCandidateTests(ScoreEntryTestBase):
    """GET scores: narrowed candidates must give exactly the legacy rows."""

    def setUp(self):
        super().setUp()
        self.assessment = self.new_assessment("Sheet")
        self.stayed = self.enroll(self.a, name="Stayed")
        self.moved_out_after = self.enroll(self.a, name="MovedOutAfter")
        self.transfer(self.moved_out_after, self.a, self.b, date(2026, 7, 1))
        self.moved_in_before = self.enroll(self.b, name="MovedInBefore")
        self.transfer(self.moved_in_before, self.b, self.a, date(2026, 5, 1))
        self.multi_in_a = self.enroll(self.a, name="MultiInA")
        self.transfer(self.multi_in_a, self.a, self.b, date(2026, 3, 1))
        self.transfer(self.multi_in_a, self.b, self.a, date(2026, 5, 15))
        self.transfer(self.multi_in_a, self.a, self.c, date(2026, 7, 1))
        self.multi_in_b = self.enroll(self.b, name="MultiInB")
        self.transfer(self.multi_in_b, self.b, self.a, date(2026, 3, 1))
        self.transfer(self.multi_in_b, self.a, self.b, date(2026, 4, 1))
        # Legacy data: scored under A while its own history never mentions A.
        self.scored = self.enroll(self.c, name="Scored")
        StudentScore.objects.create(
            assessment=self.assessment, enrollment=self.scored, recorded_section=self.a,
            score=Decimal("11"), updated_by=self.admin,
        )
        self.other_section = self.enroll(self.c, name="OtherSection")
        self.late = self.enroll(self.a, name="Late", enrollment_date=date(2026, 7, 1))
        self.noise = [self.enroll(self.c, name=f"Noise{index:02d}") for index in range(10)]

    def row_ids(self, section):
        return {row["enrollment"] for row in get_assessment_score_rows(assessment=self.assessment, section=section)}

    def test_membership_on_the_assessment_date(self):
        expectations = {
            "stayed in the section": (self.stayed, {self.a}),
            "moved out after the date": (self.moved_out_after, {self.a}),
            "moved in before the date": (self.moved_in_before, {self.a}),
            "several transfers": (self.multi_in_a, {self.a}),
            "several transfers ending elsewhere": (self.multi_in_b, {self.b}),
            # Listed under A by its score, and under C (unscored) by its own history.
            "existing score": (self.scored, {self.a, self.c}),
            "other section": (self.other_section, {self.c}),
        }
        rows = {section.id: self.row_ids(section) for section in (self.a, self.b, self.c)}
        for case, (enrollment, sections) in expectations.items():
            with self.subTest(case=case):
                self.assertEqual(
                    {sid for sid, ids in rows.items() if enrollment.id in ids},
                    {section.id for section in sections},
                )
        self.assertNotIn(self.late.id, rows[self.a.id])

    def test_rows_match_legacy_query_for_every_section(self):
        for section in (self.a, self.b, self.c):
            with self.subTest(section=section.name):
                self.assertEqual(
                    get_assessment_score_rows(assessment=self.assessment, section=section),
                    legacy_score_rows(assessment=self.assessment, section=section),
                )

    def test_candidates_exclude_unrelated_school_enrollments(self):
        with patch(
            "grades.selectors.get_enrollment_section_id_on_date",
            wraps=get_enrollment_section_id_on_date,
        ) as decide:
            get_assessment_score_rows(assessment=self.assessment, section=self.a)

        checked = {call.kwargs["enrollment"].id for call in decide.call_args_list}
        self.assertTrue(checked.isdisjoint({enrollment.id for enrollment in self.noise}))
        self.assertNotIn(self.other_section.id, checked)
        self.assertLess(len(checked), Enrollment.objects.filter(academic_year=self.year).count())
        # The historical decision still runs for every narrowed candidate.
        self.assertTrue({self.moved_out_after.id, self.multi_in_b.id} <= checked)


class BulkScoreEntryTests(ScoreEntryTestBase):
    def setUp(self):
        super().setUp()
        self.students = [self.enroll(self.a) for _ in range(8)]

    def reads(self, queries):
        return [q for q in queries if q["sql"].lstrip().upper().startswith("SELECT")]

    def assert_reads_constant_and_writes_per_record(self, user):
        """Reads must not depend on N; each record adds exactly its score write and audit insert."""
        warmup, small_assessment, large_assessment = (
            self.new_assessment(f"{user.username}-{label}") for label in ("warmup", "small", "large")
        )
        self.post_bulk(user, warmup, self.a, [(self.students[0], "1.00")])

        created = {}
        for assessment, count in ((small_assessment, 2), (large_assessment, 8)):
            response, queries = self.post_bulk(
                user, assessment, self.a, [(enrollment, "10.00") for enrollment in self.students[:count]],
            )
            self.assertEqual(response.status_code, 200, response.data)
            created[count] = queries
        self.assertEqual(len(self.reads(created[8])), len(self.reads(created[2])))
        # Per record: one StudentScore INSERT and one ScoreAuditLog INSERT.
        self.assertEqual(len(created[8]) - len(created[2]), 2 * 6)

        updated = {}
        for assessment, count in ((small_assessment, 2), (large_assessment, 8)):
            response, queries = self.post_bulk(
                user, assessment, self.a, [(enrollment, "12.00") for enrollment in self.students[:count]],
            )
            self.assertEqual(response.status_code, 200, response.data)
            updated[count] = queries
        self.assertEqual(len(self.reads(updated[8])), len(self.reads(updated[2])))
        # Per record: one StudentScore UPDATE and one ScoreAuditLog INSERT.
        self.assertEqual(len(updated[8]) - len(updated[2]), 2 * 6)

    def test_query_growth_is_only_writes_for_admin(self):
        self.assert_reads_constant_and_writes_per_record(self.admin)

    def test_query_growth_is_only_writes_for_teacher(self):
        self.assert_reads_constant_and_writes_per_record(self.teacher)

    def test_query_growth_is_only_writes_for_supervisor(self):
        self.assert_reads_constant_and_writes_per_record(self.supervisor)

    def test_supervisor_scope_is_loaded_once_per_request(self):
        assessment = self.new_assessment("Scope once")
        response, queries = self.post_bulk(
            self.supervisor, assessment, self.a, [(enrollment, "9.00") for enrollment in self.students],
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(sum(SCOPE_TABLE in q["sql"] for q in queries), 1)

        with CaptureQueriesContext(connection) as ctx:
            sheet = self.client.get(f"/api/v1/grades/assessments/{assessment.id}/scores/", {"section": str(self.a.id)})
        self.assertEqual(sheet.status_code, 200)
        self.assertEqual(sum(SCOPE_TABLE in q["sql"] for q in ctx.captured_queries), 1)

    def test_create_update_and_mixed_requests(self):
        assessment = self.new_assessment("Mixed")
        first, second, third = self.students[:3]

        response, _ = self.post_bulk(self.admin, assessment, self.a, [(first, "10.00"), (second, None)])
        self.assertEqual(response.status_code, 200, response.data)
        response, _ = self.post_bulk(self.admin, assessment, self.a, [(third, "7.50"), (first, "14.00"), (second, None)])
        self.assertEqual(response.status_code, 200, response.data)

        scores = dict(StudentScore.objects.filter(assessment=assessment).values_list("enrollment_id", "score"))
        self.assertEqual(scores, {first.id: Decimal("14.00"), second.id: None, third.id: Decimal("7.50")})
        self.assertEqual(StudentScore.objects.filter(assessment=assessment, recorded_section=self.a).count(), 3)
        audits = ScoreAuditLog.objects.filter(assessment=assessment)
        self.assertEqual(audits.count(), 5)
        self.assertTrue(audits.filter(enrollment=first, old_score=Decimal("10.00"), new_score=Decimal("14.00")).exists())
        self.assertTrue(audits.filter(enrollment=third, old_score=None, new_score=Decimal("7.50")).exists())
        # Unchanged resubmission is still audited, as before.
        self.assertEqual(audits.filter(enrollment=second).count(), 2)

    def test_invalid_record_rolls_back_the_whole_request(self):
        assessment = self.new_assessment("Rollback")
        response, _ = self.post_bulk(
            self.admin, assessment, self.a, [(self.students[0], "10.00"), (self.students[1], "25.00")],
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(StudentScore.objects.filter(assessment=assessment).exists())
        self.assertFalse(ScoreAuditLog.objects.filter(assessment=assessment).exists())

    def test_missing_and_duplicate_enrollments_are_rejected_without_writes(self):
        assessment = self.new_assessment("Bad ids")
        missing, _ = self.post_bulk(self.admin, assessment, self.a, [(self.students[0], "10.00"), (uuid.uuid4(), "10.00")])
        duplicate, _ = self.post_bulk(self.admin, assessment, self.a, [(self.students[0], "10.00"), (self.students[0], "11.00")])

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("يجب إرسال سجلات غير مكررة لطالب واحد على الأقل.", str(duplicate.data))
        self.assertFalse(StudentScore.objects.filter(assessment=assessment).exists())

    def test_section_membership_on_assessment_date_is_enforced(self):
        assessment = self.new_assessment("Membership")
        moved_out_after = self.enroll(self.a)
        self.transfer(moved_out_after, self.a, self.b, date(2026, 7, 1))
        moved_in_before = self.enroll(self.b)
        self.transfer(moved_in_before, self.b, self.a, date(2026, 5, 1))
        left_before = self.enroll(self.a)
        self.transfer(left_before, self.a, self.b, date(2026, 5, 1))
        other_section = self.enroll(self.c)

        accepted, _ = self.post_bulk(self.admin, assessment, self.a, [(moved_out_after, "10.00"), (moved_in_before, "11.00")])
        self.assertEqual(accepted.status_code, 200, accepted.data)
        for enrollment in (left_before, other_section):
            with self.subTest(enrollment=enrollment.student.first_name):
                rejected, _ = self.post_bulk(self.admin, assessment, self.a, [(enrollment, "10.00")])
                self.assertEqual(rejected.status_code, 400)
                self.assertIn("الطالب لم يكن يتبع شعبة التقييم في تاريخ التقييم.", str(rejected.data))
        self.assertEqual(
            set(StudentScore.objects.filter(assessment=assessment).values_list("enrollment_id", flat=True)),
            {moved_out_after.id, moved_in_before.id},
        )

    def test_role_access_is_unchanged(self):
        assessment = self.new_assessment("Roles")
        for user in (self.admin, self.teacher, self.supervisor):
            with self.subTest(role=user.role):
                response, _ = self.post_bulk(user, assessment, self.a, [(self.students[0], "10.00")])
                self.assertEqual(response.status_code, 200, response.data)

        unassigned, _ = self.post_bulk(self.teacher, assessment, self.b, [(self.enroll(self.b), "10.00")])
        self.assertEqual(unassigned.status_code, 403)
        self.assertIn("GRADE_ASSIGNMENT_REQUIRED", str(unassigned.data))

        other_grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PREPARATORY, name="Perf preparatory")
        outside = self.enroll(Section.objects.create(academic_year=self.year, grade_level=other_grade, name="P"))
        denied, _ = self.post_bulk(self.supervisor, assessment, self.a, [(self.students[1], "10.00"), (outside, "10.00")])
        self.assertEqual(denied.status_code, 403)
        self.assertIn("SUPERVISOR_ACADEMIC_SCOPE_DENIED", str(denied.data))
        self.assertFalse(StudentScore.objects.filter(assessment=assessment, enrollment=self.students[1]).exists())

    def test_response_matches_the_score_sheet(self):
        assessment = self.new_assessment("Response")
        response, _ = self.post_bulk(self.admin, assessment, self.a, [(self.students[0], "10.00"), (self.students[1], None)])
        self.assertEqual(response.status_code, 200, response.data)
        sheet = self.client.get(f"/api/v1/grades/assessments/{assessment.id}/scores/", {"section": str(self.a.id)})

        self.assertEqual(response.data["data"], sheet.data["data"])
        self.assertEqual(
            set(response.data["data"]["records"][0]),
            {"enrollment", "student", "student_display", "score", "updated_by", "updated_by_username", "updated_at"},
        )
        self.assertEqual(
            [row["enrollment"] for row in response.data["data"]["records"]],
            [str(row["enrollment"]) for row in legacy_score_rows(assessment=assessment, section=self.a)],
        )


class BulkScoresSerializerContractTests(ScoreEntryTestBase):
    def payload(self, *values):
        return {"section": str(self.a.id), "records": [{"enrollment": value, "score": "10.00"} for value in values]}

    def test_errors_match_the_per_item_primary_key_field(self):
        valid = str(self.enroll(self.a).id)
        payloads = {
            "missing id": self.payload(valid, str(uuid.uuid4())),
            "malformed id": self.payload("not-a-uuid", valid),
            "integer id": self.payload(5),
            "null id": self.payload(None),
            "records not a list": {"section": str(self.a.id), "records": "x"},
            "record not an object": {"section": str(self.a.id), "records": ["x"]},
            "empty records": {"section": str(self.a.id), "records": []},
        }
        for case, data in payloads.items():
            with self.subTest(case=case):
                current = BulkAssessmentScoresSerializer(data=data)
                legacy = LegacyBulkScoresSerializer(data=data)
                self.assertFalse(current.is_valid())
                self.assertFalse(legacy.is_valid())
                self.assertEqual(current.errors, legacy.errors)

    def test_enrollments_load_once_in_request_order_with_stage_path(self):
        enrollments = [self.enroll(self.a) for _ in range(8)]

        def validate(subset):
            serializer = BulkAssessmentScoresSerializer(data=self.payload(*[str(e.id) for e in subset]))
            with CaptureQueriesContext(connection) as ctx:
                self.assertTrue(serializer.is_valid(), serializer.errors)
            return serializer, len(ctx.captured_queries)

        _, small = validate(enrollments[:2])
        serializer, large = validate(list(reversed(enrollments)))

        self.assertEqual(small, large)
        records = serializer.validated_data["records"]
        self.assertEqual([record["enrollment"].id for record in records], [e.id for e in reversed(enrollments)])
        with self.assertNumQueries(0):
            stages = {record["enrollment"].section.grade_level.stage for record in records}
        self.assertEqual(stages, {GradeLevel.Stage.PRIMARY})
