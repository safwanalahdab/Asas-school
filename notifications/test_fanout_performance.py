import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from academics.models import AcademicYear, GradeLevel, GradeSubject, Section, Subject, Term
from announcements.models import Announcement
from announcements.services import notify_announcement_published
from attendance.models import AttendanceRecord, AttendanceSheet
from attendance.services import _notify_final_absences
from grades.models import StudentScore
from grades.services import create_assessment, publish_section_assessments
from homework.models import Homework
from homework.services import notify_homework_created
from students.models import Enrollment, GuardianStudent, Student
from teaching.models import TeacherAssignment

from .models import Notification, PushDevice
from .services import create_notification, create_notifications


User = get_user_model()

PUSH_ON = override_settings(FIREBASE_PUSH_ENABLED=True)


class FanoutFixture(TestCase):
    def setUp(self):
        self.counter = 0
        self.today = timezone.localdate()
        self.admin = User.objects.create_user(
            username="fanout-admin", password="x", role=User.Role.SCHOOL_ADMIN, must_change_password=False,
        )
        self.year = AcademicYear.objects.create(
            start_date=self.today - timedelta(days=60), end_date=self.today + timedelta(days=60),
            status=AcademicYear.Status.ACTIVE,
        )
        self.grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="Fanout")
        self.subject = Subject.objects.create(name="Fanout subject")
        self.plan = GradeSubject.objects.create(academic_year=self.year, grade_level=self.grade, subject=self.subject)

    def guardian(self):
        self.counter += 1
        return User.objects.create_user(
            username=f"fanout-guardian-{self.counter}", password="x",
            role=User.Role.GUARDIAN, must_change_password=False,
        )

    def section(self, name):
        return Section.objects.create(academic_year=self.year, grade_level=self.grade, name=name)

    def family(self, section, *, guardian=None):
        """A guardian with one actively linked, enrolled child."""
        guardian = guardian or self.guardian()
        self.counter += 1
        student = Student.objects.create(
            first_name=f"Child{self.counter:03d}", last_name="Fanout",
            birth_date=date(2015, 1, 1), gender=Student.Gender.MALE,
        )
        GuardianStudent.objects.create(guardian=guardian, student=student)
        enrollment = Enrollment.objects.create(
            student=student, academic_year=self.year, section=section, enrollment_date=self.year.start_date,
        )
        return guardian, student, enrollment

    def device(self, user, *, active=True):
        return PushDevice.objects.create(
            user=user, installation_id=uuid.uuid4(), fcm_token=f"token-{uuid.uuid4()}",
            platform=PushDevice.Platform.ANDROID, is_active=active, last_seen_at=timezone.now(),
        )

    def spec(self, guardian, student=None, *, event_key=None, title="  Title  "):
        return dict(
            recipient=guardian, notification_type=Notification.NotificationType.GENERAL,
            title=title, body="  Body  ", student=student,
            resource_type="  general  ", resource_id=uuid.uuid4(),
            event_key=event_key or f"fanout:{uuid.uuid4()}",
        )


@PUSH_ON
class CreateNotificationsTests(FanoutFixture):
    def specs_for(self, count, section_name):
        section = self.section(section_name)
        return [self.spec(guardian, student) for guardian, student, _ in (self.family(section) for _ in range(count))]

    def test_query_count_and_rows_do_not_grow_with_recipients(self):
        small_specs, large_specs = self.specs_for(3, "S"), self.specs_for(30, "L")
        with CaptureQueriesContext(connection) as small:
            small_result = create_notifications(small_specs)
        with CaptureQueriesContext(connection) as large:
            large_result = create_notifications(large_specs)

        self.assertEqual(len(large), len(small))
        self.assertEqual(len(small_result), 3)
        self.assertEqual(len(large_result), 30)
        self.assertEqual(Notification.objects.count(), 33)
        self.assertTrue(all(created for _, created in small_result + large_result))

    def test_duplicate_and_existing_events_create_one_notification_each(self):
        guardian, student, _ = self.family(self.section("D"))
        existing, _ = create_notification(**self.spec(guardian, student, event_key="fanout:existing"))
        repeated = self.spec(guardian, student, event_key="fanout:repeated")

        results = create_notifications([
            repeated, dict(repeated), self.spec(guardian, student, event_key="fanout:existing"),
        ])

        (first, first_created), (second, second_created), (third, third_created) = results
        self.assertTrue(first_created)
        self.assertEqual((second.pk, second_created), (first.pk, False))
        self.assertEqual((third.pk, third_created), (existing.pk, False))
        self.assertEqual(Notification.objects.filter(recipient=guardian).count(), 2)
        self.assertEqual(
            set(Notification.objects.filter(recipient=guardian).values_list("push_status", flat=True)),
            {Notification.PushStatus.PENDING},
        )

    def test_content_matches_single_create_notification(self):
        guardian, student, _ = self.family(self.section("C"))
        resource_id = uuid.uuid4()
        values = dict(self.spec(guardian, student), resource_id=resource_id)
        single, _ = create_notification(**dict(values, event_key="fanout:single"))
        (bulk, _), = create_notifications([dict(values, event_key="fanout:bulk")])
        bulk.refresh_from_db()

        fields = (
            "recipient_id", "notification_type", "title", "body", "student_id",
            "resource_type", "resource_id", "is_read", "read_at", "push_status", "push_attempts",
        )
        self.assertEqual(
            {field: getattr(bulk, field) for field in fields},
            {field: getattr(single, field) for field in fields},
        )
        self.assertEqual((bulk.title, bulk.body, bulk.resource_type), ("Title", "Body", "general"))
        self.assertFalse(bulk.is_read)

    def test_validation_errors_match_single_path(self):
        guardian, student, _ = self.family(self.section("V"))
        stranger = self.guardian()
        teacher = User.objects.create_user(username="fanout-teacher", password="x", role=User.Role.TEACHER)
        inactive_student = Student.objects.create(
            first_name="Inactive", last_name="Fanout", birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE, is_active=False,
        )
        cases = {
            "unlinked student": self.spec(stranger, student),
            "inactive student": self.spec(guardian, inactive_student),
            "non-guardian recipient": self.spec(teacher),
            "invalid type": dict(self.spec(guardian), notification_type="nope"),
            "blank title": self.spec(guardian, title="   "),
            "title too long": self.spec(guardian, title="x" * 201),
            "half resource pair": dict(self.spec(guardian), resource_id=None),
        }
        for case, spec in cases.items():
            with self.subTest(case=case):
                with self.assertRaises(ValidationError) as single:
                    create_notification(**spec)
                with self.assertRaises(ValidationError) as bulk:
                    create_notifications([self.spec(guardian, student), spec])
                self.assertEqual(bulk.exception.message_dict, single.exception.message_dict)
        self.assertFalse(Notification.objects.exists())

    @patch("firebase_admin.messaging.send_each")
    @patch("firebase_admin.messaging.send")
    def test_new_notifications_are_pending_and_nothing_runs_after_commit(self, send, send_each):
        specs = self.specs_for(4, "P")
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            results = create_notifications(specs)
        self.assertEqual(callbacks, [])
        now = timezone.now()
        for notification in Notification.objects.filter(pk__in=[n.pk for n, _ in results]):
            self.assertEqual(notification.push_status, Notification.PushStatus.PENDING)
            self.assertEqual(notification.push_attempts, 0)
            self.assertLessEqual(notification.push_next_attempt_at, now)
        send.assert_not_called()
        send_each.assert_not_called()

    @override_settings(FIREBASE_PUSH_ENABLED=False)
    def test_disabled_push_creates_skipped_notifications(self):
        results = create_notifications(self.specs_for(2, "K"))
        self.assertEqual(
            set(Notification.objects.filter(pk__in=[n.pk for n, _ in results]).values_list("push_status", flat=True)),
            {Notification.PushStatus.SKIPPED},
        )

    @patch("firebase_admin.messaging.send_each")
    @patch("firebase_admin.messaging.send")
    def test_rollback_leaves_no_notifications(self, send, send_each):
        specs = self.specs_for(3, "R")
        with self.assertRaises(RuntimeError), transaction.atomic():
            create_notifications(specs)
            raise RuntimeError("rollback")
        self.assertFalse(Notification.objects.exists())
        send.assert_not_called()
        send_each.assert_not_called()

    def test_insert_race_falls_back_to_single_idempotent_path(self):
        specs = self.specs_for(3, "F")
        with patch.object(Notification.objects, "bulk_create", side_effect=IntegrityError("race")):
            results = create_notifications(specs)
        self.assertEqual(Notification.objects.count(), 3)
        self.assertTrue(all(created for _, created in results))
        self.assertEqual(
            set(Notification.objects.values_list("push_status", flat=True)),
            {Notification.PushStatus.PENDING},
        )


class FanoutCallerTests(FanoutFixture):
    """Fan-out callers: constant queries, same recipients, payload unchanged."""

    def families(self, count, section_name):
        section = self.section(section_name)
        return section, [self.family(section) for _ in range(count)]

    def test_announcement_queries_constant_and_recipients_unchanged(self):
        def run(count, name):
            section, families = self.families(count, name)
            announcement = Announcement.objects.create(
                scope=Announcement.Scope.SECTIONS, title="T", content="C",
                publish_date=self.today, created_by=self.admin,
            )
            announcement.sections.add(section)
            with CaptureQueriesContext(connection) as ctx:
                notifications = notify_announcement_published(announcement)
            self.assertEqual({n.recipient_id for n in notifications}, {g.id for g, _, _ in families})
            return ctx, announcement

        small, _ = run(3, "AS")
        large, announcement = run(15, "AL")
        self.assertEqual(len(large), len(small))
        notification = Notification.objects.filter(resource_id=announcement.id).first()
        self.assertEqual(
            (notification.notification_type, notification.title, notification.student_id, notification.event_key),
            ("announcement", "إعلان جديد", None, f"announcement:{announcement.id}:published"),
        )
        # Re-publishing is idempotent.
        self.assertEqual(len(notify_announcement_published(announcement)), 15)
        self.assertEqual(Notification.objects.filter(resource_id=announcement.id).count(), 15)

    def test_homework_queries_constant_and_one_guardian_gets_one_per_child(self):
        def run(count, name):
            section, families = self.families(count, name)
            shared_guardian = families[0][0]
            self.family(section, guardian=shared_guardian)
            assignment = TeacherAssignment.objects.create(
                teacher=self.admin, grade_subject=self.plan, section=section, start_date=self.year.start_date,
            )
            homework = Homework.objects.create(
                teacher_assignment=assignment, title="H", description="D",
                homework_date=self.today, due_date=self.today, created_by=self.admin,
            )
            with CaptureQueriesContext(connection) as ctx:
                notifications = notify_homework_created(homework)
            self.assertEqual(len(notifications), count + 1)
            self.assertEqual(
                {n.event_key for n in notifications},
                {f"homework:{homework.id}:student:{e.student_id}" for e in Enrollment.objects.filter(section=section)},
            )
            return ctx

        self.assertEqual(len(run(15, "HL")), len(run(3, "HS")))

    def test_attendance_absences_queries_constant(self):
        def run(count, name):
            section, families = self.families(count, name)
            sheet = AttendanceSheet.objects.create(section=section, attendance_date=self.today, created_by=self.admin)
            for _, _, enrollment in families:
                AttendanceRecord.objects.create(
                    sheet=sheet, enrollment=enrollment, status=AttendanceRecord.Status.ABSENT,
                    absence_type=AttendanceRecord.AbsenceType.UNEXCUSED,
                )
            records = list(AttendanceRecord.objects.select_related("enrollment").filter(sheet=sheet))
            with CaptureQueriesContext(connection) as ctx:
                _notify_final_absences(records)
            self.assertEqual(
                set(Notification.objects.filter(resource_id__in=[r.id for r in records]).values_list("event_key", flat=True)),
                {f"attendance:{r.id}:absent" for r in records},
            )
            return ctx

        self.assertEqual(len(run(15, "TL")), len(run(3, "TS")))

    def test_grade_publish_queries_constant(self):
        term = Term.objects.create(
            academic_year=self.year, number=Term.Number.FIRST,
            start_date=self.year.start_date, end_date=self.year.end_date,
        )

        def run(count, name):
            section, families = self.families(count, name)
            assessment = create_assessment(
                section=section, grade_subject=self.plan, term=term, title=f"Publish {name}",
                max_score=Decimal("20"), assessment_date=self.today, actor=self.admin,
            )
            for _, _, enrollment in families:
                StudentScore.objects.create(
                    assessment=assessment, enrollment=enrollment, recorded_section=section,
                    score=Decimal("15"), updated_by=self.admin,
                )
            with CaptureQueriesContext(connection) as ctx:
                result = publish_section_assessments(section=section, term=term, actor=self.admin)
            self.assertEqual(result["published_count"], 1)
            self.assertEqual(
                set(Notification.objects.filter(notification_type="grades", student__in=[s for _, s, _ in families])
                    .values_list("recipient_id", flat=True)),
                {g.id for g, _, _ in families},
            )
            return ctx

        self.assertEqual(len(run(15, "GL")), len(run(3, "GS")))

    @PUSH_ON
    @patch("firebase_admin.messaging.send_each", side_effect=RuntimeError("down"))
    @patch("firebase_admin.messaging.send", side_effect=RuntimeError("down"))
    def test_firebase_outage_does_not_undo_the_operation(self, send, send_each):
        section, families = self.families(3, "O")
        for guardian, _, _ in families:
            self.device(guardian)
        announcement = Announcement.objects.create(
            scope=Announcement.Scope.SECTIONS, title="T", content="C",
            publish_date=self.today, created_by=self.admin,
        )
        announcement.sections.add(section)
        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                notify_announcement_published(announcement)
        self.assertEqual(
            list(Notification.objects.filter(resource_id=announcement.id).values_list("push_status", flat=True)),
            [Notification.PushStatus.PENDING] * 3,
        )
        self.assertTrue(Announcement.objects.filter(pk=announcement.pk).exists())
        send.assert_not_called()
        send_each.assert_not_called()
