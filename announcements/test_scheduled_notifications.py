import threading
from datetime import date, datetime, time, timedelta
from io import StringIO
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, Section
from notifications.models import Notification
from students.models import Enrollment, GuardianStudent, Student

from . import services
from .models import Announcement
from .services import notify_due_announcements
from .views import AnnouncementViewSet


User = get_user_model()

URL = "/api/v1/announcements/"
SCHEDULED_SETTINGS = override_settings(
    FIREBASE_PUSH_ENABLED=True,
    ANNOUNCEMENT_NOTIFY_HOUR=7,
)


def at(day, hour, minute=0):
    """An aware datetime at the given local (TIME_ZONE) time."""
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


def clock(moment):
    # timezone.localdate() and localtime() read timezone.now() too.
    return patch("django.utils.timezone.now", return_value=moment)


class ScheduledFixtureMixin:
    def build_school(self):
        self.counter = 0
        self.today = timezone.localdate()
        self.tomorrow = self.today + timedelta(days=1)
        self.admin = User.objects.create_user(
            username="scheduled-announcement-admin", password="x",
            role=User.Role.SCHOOL_ADMIN, must_change_password=False,
        )
        self.year = AcademicYear.objects.create(
            start_date=self.today - timedelta(days=100),
            end_date=self.today + timedelta(days=100),
            status=AcademicYear.Status.ACTIVE,
        )
        self.grade = GradeLevel.objects.create(stage="primary", name="Scheduled")
        self.section = self.new_section("A")
        self.other_section = self.new_section("B")
        self.guardian = self.family(self.section)
        self.other_guardian = self.family(self.other_section)

    def new_section(self, name):
        return Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name=name,
        )

    def family(self, section):
        """A guardian with one actively linked, enrolled child."""
        self.counter += 1
        guardian = User.objects.create_user(
            username=f"scheduled-guardian-{self.counter}", password="x",
            role=User.Role.GUARDIAN, must_change_password=False,
        )
        student = Student.objects.create(
            first_name=f"Child{self.counter:03d}", last_name="Scheduled",
            birth_date=date(2015, 1, 1), gender=Student.Gender.MALE,
        )
        GuardianStudent.objects.create(guardian=guardian, student=student)
        Enrollment.objects.create(
            student=student, academic_year=self.year, section=section,
            enrollment_date=self.year.start_date,
        )
        return guardian

    def announcement(self, publish_date, *, sections=(), expiry_date=None):
        announcement = Announcement.objects.create(
            scope=Announcement.Scope.SECTIONS if sections else Announcement.Scope.ALL,
            title="Private scheduled title", content="Private scheduled content",
            publish_date=publish_date, expiry_date=expiry_date,
            created_by=self.admin,
        )
        announcement.sections.set(sections)
        return announcement

    def notifications(self, announcement):
        return Notification.objects.filter(resource_id=announcement.pk)

    def recipients(self, announcement):
        return set(self.notifications(announcement).values_list("recipient_id", flat=True))


@SCHEDULED_SETTINGS
class ScheduledAnnouncementNotificationTests(ScheduledFixtureMixin, TestCase):
    def setUp(self):
        self.build_school()
        self.client = APIClient()
        self.client.force_authenticate(self.admin, token={"client": "web"})

    def post(self, publish_date, *, sections=()):
        response = self.client.post(URL, {
            "scope": "sections" if sections else "all",
            "sections": [str(section.pk) for section in sections],
            "grade_levels": [], "title": "Scheduled", "content": "Private",
            "publish_date": str(publish_date),
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return Announcement.objects.get(pk=response.data["data"]["id"])

    def patch(self, announcement, data):
        response = self.client.patch(f"{URL}{announcement.pk}/", data, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        announcement.refresh_from_db()
        return response

    # 1
    def test_api_create_for_today_notifies_now_and_marks(self):
        announcement = self.post(self.today)

        self.assertEqual(
            self.recipients(announcement), {self.guardian.pk, self.other_guardian.pk},
        )
        for notification in self.notifications(announcement):
            self.assertEqual(notification.push_status, Notification.PushStatus.PENDING)
            self.assertEqual(
                notification.event_key, f"announcement:{announcement.pk}:published",
            )
        self.assertIsNotNone(announcement.publish_notified_at)

    # 2
    def test_api_create_for_tomorrow_is_deferred(self):
        announcement = self.post(self.tomorrow)

        self.assertFalse(self.notifications(announcement).exists())
        self.assertIsNone(announcement.publish_notified_at)

    # 3
    def test_job_before_notify_hour_does_nothing(self):
        announcement = self.announcement(self.tomorrow)

        with clock(at(self.tomorrow, 6, 59)):
            self.assertEqual(notify_due_announcements(), 0)

        announcement.refresh_from_db()
        self.assertFalse(self.notifications(announcement).exists())
        self.assertIsNone(announcement.publish_notified_at)

    # 4
    def test_job_from_notify_hour_notifies_every_targeted_guardian(self):
        announcement = self.announcement(self.tomorrow)
        moment = at(self.tomorrow, 7)

        with clock(moment):
            self.assertEqual(notify_due_announcements(), 1)

        announcement.refresh_from_db()
        self.assertEqual(
            self.recipients(announcement), {self.guardian.pk, self.other_guardian.pk},
        )
        self.assertEqual(
            set(self.notifications(announcement).values_list("push_status", flat=True)),
            {Notification.PushStatus.PENDING},
        )
        self.assertEqual(announcement.publish_notified_at, moment)

    # 5
    def test_second_run_handles_nothing_and_creates_no_duplicates(self):
        announcement = self.announcement(self.tomorrow)

        with clock(at(self.tomorrow, 8)):
            self.assertEqual(notify_due_announcements(), 1)
            self.assertEqual(notify_due_announcements(), 0)

        self.assertEqual(self.notifications(announcement).count(), 2)

    # 6
    def test_announcement_expired_before_the_run_is_marked_without_notifications(self):
        announcement = self.announcement(self.tomorrow, expiry_date=self.tomorrow)

        with clock(at(self.tomorrow + timedelta(days=1), 8)):
            self.assertEqual(notify_due_announcements(), 1)

        announcement.refresh_from_db()
        self.assertFalse(self.notifications(announcement).exists())
        self.assertIsNotNone(announcement.publish_notified_at)

    # 7
    def test_retargeted_scheduled_announcement_notifies_only_the_new_sections(self):
        announcement = self.post(self.tomorrow, sections=[self.section])
        self.patch(announcement, {"sections": [str(self.other_section.pk)]})
        self.assertFalse(self.notifications(announcement).exists())
        self.assertIsNone(announcement.publish_notified_at)

        with clock(at(self.tomorrow, 8)):
            self.assertEqual(notify_due_announcements(), 1)

        self.assertEqual(self.recipients(announcement), {self.other_guardian.pk})

    # 8
    def test_moving_a_scheduled_announcement_to_today_notifies_now(self):
        announcement = self.post(self.tomorrow)

        self.patch(announcement, {"publish_date": str(self.today)})

        self.assertEqual(
            self.recipients(announcement), {self.guardian.pk, self.other_guardian.pk},
        )
        self.assertIsNotNone(announcement.publish_notified_at)

    # 9
    def test_updating_a_notified_announcement_sends_nothing_new(self):
        announcement = self.post(self.today, sections=[self.section])
        notified_at = announcement.publish_notified_at

        self.patch(announcement, {
            "title": "Changed", "sections": [str(self.other_section.pk)],
        })

        self.assertEqual(self.recipients(announcement), {self.guardian.pk})
        self.assertEqual(announcement.publish_notified_at, notified_at)

    def test_update_does_not_overwrite_a_mark_set_after_the_row_was_read(self):
        announcement = self.announcement(self.today)
        marked_at = at(self.today, 0, 30)

        def job_marks_meanwhile(_serializer):
            Announcement.objects.filter(pk=announcement.pk).update(
                publish_notified_at=marked_at,
            )

        with patch.object(
            AnnouncementViewSet, "require_supervisor_targets",
            side_effect=job_marks_meanwhile,
        ):
            self.patch(announcement, {"title": "Changed"})

        self.assertEqual(announcement.publish_notified_at, marked_at)
        self.assertEqual(announcement.title, "Changed")
        self.assertFalse(self.notifications(announcement).exists())

    # 10
    def test_one_failure_is_logged_and_the_rest_are_handled(self):
        broken = self.announcement(self.tomorrow)
        healthy = self.announcement(self.tomorrow)
        original = services.notify_announcement_published

        def flaky(announcement):
            if announcement.pk == broken.pk:
                raise RuntimeError("boom")
            return original(announcement)

        with clock(at(self.tomorrow, 8)), patch(
            "announcements.services.notify_announcement_published", side_effect=flaky,
        ), self.assertLogs("announcements.services", level="ERROR") as logs:
            self.assertEqual(notify_due_announcements(), 1)

        broken.refresh_from_db()
        healthy.refresh_from_db()
        self.assertIsNone(broken.publish_notified_at)
        self.assertIsNotNone(healthy.publish_notified_at)
        self.assertEqual(self.notifications(healthy).count(), 2)
        self.assertEqual(len(logs.records), 1)
        message = logs.records[0].getMessage()
        self.assertIn(str(broken.pk), message)
        self.assertIn("RuntimeError", message)
        self.assertNotIn(broken.title, message)

        # The failed announcement is retried by the next run.
        with clock(at(self.tomorrow, 8, 5)):
            self.assertEqual(notify_due_announcements(), 1)
        self.assertEqual(self.notifications(broken).count(), 2)

    # 12
    def test_job_queries_do_not_grow_with_guardians(self):
        def run(count, name):
            section = self.new_section(name)
            for _ in range(count):
                self.family(section)
            announcement = self.announcement(self.tomorrow, sections=[section])
            with clock(at(self.tomorrow, 8)), CaptureQueriesContext(connection) as ctx:
                self.assertEqual(notify_due_announcements(), 1)
            self.assertEqual(self.notifications(announcement).count(), count)
            return ctx.captured_queries

        small = run(3, "Small")
        large = run(15, "Large")
        self.assertEqual(len(large), len(small))

    def test_command_prints_the_count_and_succeeds_when_zero(self):
        self.announcement(self.tomorrow)

        out = StringIO()
        with clock(at(self.tomorrow, 6)):
            call_command("notify_due_announcements", stdout=out)
        self.assertEqual(out.getvalue().strip(), "announcements_notified: 0")

        out = StringIO()
        with clock(at(self.tomorrow, 8)):
            call_command("notify_due_announcements", stdout=out)
        self.assertEqual(out.getvalue().strip(), "announcements_notified: 1")


# 11
@skipUnless(connection.vendor == "postgresql", "SKIP LOCKED needs PostgreSQL.")
@SCHEDULED_SETTINGS
class ScheduledAnnouncementConcurrencyTests(ScheduledFixtureMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.build_school()

    def test_two_concurrent_runs_do_not_handle_the_same_announcement(self):
        announcement = self.announcement(self.today)
        original = services.notify_announcement_published
        first_holds_lock = threading.Event()
        second_finished = threading.Event()
        results, errors = {}, []

        def slow_for_first(locked_announcement):
            # The first run keeps the row locked until the second run is done.
            if threading.current_thread().name == "first":
                first_holds_lock.set()
                second_finished.wait(10)
            return original(locked_announcement)

        def run():
            name = threading.current_thread().name
            try:
                results[name] = notify_due_announcements()
            except Exception as error:
                errors.append(error)
            finally:
                connection.close()

        with clock(at(self.today, 12)), patch(
            "announcements.services.notify_announcement_published",
            side_effect=slow_for_first,
        ):
            first = threading.Thread(target=run, name="first")
            first.start()
            self.assertTrue(first_holds_lock.wait(10))
            second = threading.Thread(target=run, name="second")
            second.start()
            second.join(10)
            second_finished.set()
            first.join(10)

        self.assertEqual(errors, [])
        self.assertEqual(results, {"first": 1, "second": 0})
        self.assertEqual(self.notifications(announcement).count(), 2)
        self.assertEqual(
            self.recipients(announcement), {self.guardian.pk, self.other_guardian.pk},
        )
        announcement.refresh_from_db()
        self.assertIsNotNone(announcement.publish_notified_at)
