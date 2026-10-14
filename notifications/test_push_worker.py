import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, connections, transaction
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from firebase_admin import exceptions as firebase_exceptions
from firebase_admin import messaging

from .models import Notification, PushDevice
from .push_services import PushAttemptResult
from .push_testing import fake_send_each, sent_tokens
from .push_worker import BatchSummary, PushWorker, claim_batch, process_batch, record_results
from .services import create_notification


User = get_user_model()

PUSH_SETTINGS = override_settings(
    FIREBASE_PUSH_ENABLED=True,
    PUSH_MAX_ATTEMPTS=6,
    PUSH_MAX_AGE_HOURS=24,
    PUSH_SEND_CHUNK_SIZE=50,
    PUSH_WORKER_BATCH_SIZE=50,
    PUSH_LEASE_SECONDS=300,
    PUSH_WORKER_POLL_SECONDS=3,
)


class PushWorkerFixture:
    def make_guardian(self, username="worker-guardian"):
        return User.objects.create_user(
            username=username, password="x",
            role=User.Role.GUARDIAN, must_change_password=False,
        )

    def device(self, user):
        return PushDevice.objects.create(
            user=user, installation_id=uuid.uuid4(), fcm_token=f"token-{uuid.uuid4()}",
            platform=PushDevice.Platform.ANDROID, last_seen_at=timezone.now(),
        )

    def notify(self, guardian, title="Title"):
        notification, _ = create_notification(
            recipient=guardian, notification_type=Notification.NotificationType.GENERAL,
            title=title, body="Body",
        )
        return notification

    def reload(self, notification):
        return Notification.objects.get(pk=notification.pk)


@PUSH_SETTINGS
@patch("notifications.push_services.get_firebase_app", return_value=object())
class PushWorkerTests(PushWorkerFixture, TestCase):
    def setUp(self):
        self.guardian = self.make_guardian()

    def run_batch(self, errors_by_token=None, *, expect_batch=True):
        with patch(
            "notifications.push_services.messaging.send_each",
            side_effect=fake_send_each(errors_by_token),
        ) as send_each:
            if expect_batch:
                with self.assertLogs("notifications", level="INFO") as logs:
                    summary = process_batch()
                self.output = "\n".join(logs.output)
            else:
                with self.assertNoLogs("notifications", level="INFO"):
                    summary = process_batch()
        return summary, send_each

    def test_full_success_is_sent_after_one_attempt(self, _app):
        first, second = self.device(self.guardian), self.device(self.guardian)
        notification = self.notify(self.guardian)

        summary, send_each = self.run_batch()

        row = self.reload(notification)
        self.assertEqual(row.push_status, Notification.PushStatus.SENT)
        self.assertEqual(row.push_attempts, 1)
        self.assertIsNotNone(row.push_sent_at)
        self.assertEqual(row.push_last_error, "")
        self.assertIsNone(row.push_lease_token)
        self.assertIsNone(row.push_locked_until)
        self.assertCountEqual(row.push_delivered_device_ids, [str(first.id), str(second.id)])
        self.assertCountEqual(sent_tokens(send_each), [first.fcm_token, second.fcm_token])
        self.assertEqual(summary, BatchSummary(claimed=1, sent=1))
        self.assertIn(
            "claimed=1 sent=1 retry=0 failed=0 skipped=0 expired=0 lease_lost=0",
            self.output,
        )

    def test_message_keeps_data_keys_and_adds_collapse_ids(self, _app):
        self.device(self.guardian)
        notification = self.notify(self.guardian)

        _summary, send_each = self.run_batch()

        message, = send_each.call_args.args[0]
        self.assertEqual(
            set(message.data),
            {"notification_id", "type", "student_id", "resource_type", "resource_id"},
        )
        self.assertEqual(message.data["notification_id"], str(notification.id))
        self.assertEqual(message.android.collapse_key, str(notification.id))
        self.assertEqual(message.android.notification.tag, str(notification.id))
        self.assertEqual(message.apns.headers, {"apns-collapse-id": str(notification.id)})

    def test_unregistered_device_is_disabled_and_delivered_device_is_not_resent(self, _app):
        dead, alive = self.device(self.guardian), self.device(self.guardian)
        notification = self.notify(self.guardian)

        self.run_batch({dead.fcm_token: messaging.UnregisteredError("unregistered")})

        dead.refresh_from_db()
        self.assertFalse(dead.is_active)
        row = self.reload(notification)
        self.assertEqual(row.push_status, Notification.PushStatus.SENT)
        self.assertEqual(row.push_delivered_device_ids, [str(alive.id)])

        summary, send_each = self.run_batch(expect_batch=False)
        self.assertEqual(summary.claimed, 0)
        send_each.assert_not_called()

    def test_transient_error_retries_later_and_only_to_the_failed_device(self, _app):
        failing, ok = self.device(self.guardian), self.device(self.guardian)
        notification = self.notify(self.guardian)

        before = timezone.now()
        summary, _send_each = self.run_batch(
            {failing.fcm_token: firebase_exceptions.UnavailableError("unavailable")}
        )
        after = timezone.now()

        row = self.reload(notification)
        self.assertEqual(summary.retry, 1)
        self.assertEqual(row.push_status, Notification.PushStatus.PENDING)
        self.assertEqual(row.push_attempts, 1)
        self.assertEqual(row.push_last_error, "UnavailableError")
        self.assertEqual(row.push_delivered_device_ids, [str(ok.id)])
        self.assertIsNone(row.push_lease_token)
        self.assertGreaterEqual(row.push_next_attempt_at, before + timedelta(seconds=30))
        self.assertLessEqual(row.push_next_attempt_at, after + timedelta(seconds=30))

        # Not due yet.
        summary, send_each = self.run_batch(expect_batch=False)
        self.assertEqual(summary.claimed, 0)
        send_each.assert_not_called()

        Notification.objects.filter(pk=notification.pk).update(
            push_next_attempt_at=timezone.now() - timedelta(seconds=1)
        )
        _summary, send_each = self.run_batch()
        self.assertEqual(sent_tokens(send_each), [failing.fcm_token])
        row = self.reload(notification)
        self.assertEqual(row.push_status, Notification.PushStatus.SENT)
        self.assertEqual(row.push_attempts, 2)
        self.assertCountEqual(row.push_delivered_device_ids, [str(ok.id), str(failing.id)])

    def test_last_allowed_attempt_failing_marks_failed(self, _app):
        device = self.device(self.guardian)
        notification = self.notify(self.guardian)
        Notification.objects.filter(pk=notification.pk).update(push_attempts=5)

        summary, _send_each = self.run_batch(
            {device.fcm_token: firebase_exceptions.UnavailableError("unavailable")}
        )

        row = self.reload(notification)
        self.assertEqual(summary.failed, 1)
        self.assertEqual(row.push_status, Notification.PushStatus.FAILED)
        self.assertEqual(row.push_attempts, 6)
        self.assertEqual(row.push_last_error, "UnavailableError")

    def test_old_pending_notification_expires_without_calling_firebase(self, _app):
        self.device(self.guardian)
        old = self.notify(self.guardian, "Old")
        fresh_leased = self.notify(self.guardian, "Leased")
        Notification.objects.filter(pk__in=[old.pk, fresh_leased.pk]).update(
            created_at=timezone.now() - timedelta(hours=25)
        )
        # A row another worker is sending right now is left to that worker.
        Notification.objects.filter(pk=fresh_leased.pk).update(
            push_lease_token=uuid.uuid4(),
            push_locked_until=timezone.now() + timedelta(minutes=1),
        )

        summary, send_each = self.run_batch()

        self.assertEqual(summary, BatchSummary(expired=1))
        self.assertEqual(self.reload(old).push_status, Notification.PushStatus.EXPIRED)
        self.assertEqual(self.reload(fresh_leased).push_status, Notification.PushStatus.PENDING)
        send_each.assert_not_called()

    def test_expired_lease_is_claimed_again(self, _app):
        self.device(self.guardian)
        notification = self.notify(self.guardian)
        Notification.objects.filter(pk=notification.pk).update(
            push_lease_token=uuid.uuid4(),
            push_locked_until=timezone.now() - timedelta(seconds=1),
        )

        summary, _send_each = self.run_batch()

        self.assertEqual(summary.sent, 1)
        self.assertEqual(self.reload(notification).push_status, Notification.PushStatus.SENT)

    def test_active_lease_is_not_claimed(self, _app):
        self.device(self.guardian)
        notification = self.notify(self.guardian)
        token = uuid.uuid4()
        Notification.objects.filter(pk=notification.pk).update(
            push_lease_token=token,
            push_locked_until=timezone.now() + timedelta(minutes=1),
        )

        summary, send_each = self.run_batch(expect_batch=False)

        self.assertEqual(summary.claimed, 0)
        send_each.assert_not_called()
        row = self.reload(notification)
        self.assertEqual(row.push_status, Notification.PushStatus.PENDING)
        self.assertEqual(row.push_lease_token, token)

    @override_settings(PUSH_WORKER_BATCH_SIZE=2)
    def test_claim_leases_oldest_due_rows_up_to_batch_size(self, _app):
        now = timezone.now()
        not_due = self.notify(self.guardian, "Not due")
        oldest, middle, newest = (self.notify(self.guardian, title) for title in ("A", "B", "C"))
        for minutes, notification in ((40, not_due), (30, oldest), (20, middle), (10, newest)):
            Notification.objects.filter(pk=notification.pk).update(
                created_at=now - timedelta(minutes=minutes)
            )
        Notification.objects.filter(pk=not_due.pk).update(
            push_next_attempt_at=now + timedelta(minutes=5)
        )

        batch = claim_batch()

        self.assertEqual([n.pk for n in batch.notifications], [oldest.pk, middle.pk])
        for notification in (oldest, middle):
            row = self.reload(notification)
            self.assertEqual(row.push_lease_token, batch.lease_token)
            self.assertGreater(row.push_locked_until, now + timedelta(seconds=290))
        self.assertIsNone(self.reload(newest).push_lease_token)
        self.assertIsNone(self.reload(not_due).push_lease_token)

    def test_stale_worker_cannot_overwrite_the_new_owner(self, _app):
        notification = self.notify(self.guardian)
        stale = claim_batch()
        Notification.objects.filter(pk=notification.pk).update(
            push_locked_until=timezone.now() - timedelta(seconds=1)
        )
        current = claim_batch()
        self.assertEqual([n.pk for n in current.notifications], [notification.pk])
        self.assertNotEqual(current.lease_token, stale.lease_token)

        retry = PushAttemptResult(
            notification_id=notification.pk,
            status=Notification.PushStatus.PENDING,
            attempts=1,
            delivered_device_ids=[],
            next_attempt_at=timezone.now() + timedelta(seconds=30),
            error="UnavailableError",
        )
        with self.assertLogs("notifications.push_worker", level="WARNING"):
            self.assertEqual(record_results([retry], lease_token=stale.lease_token)["lease_lost"], 1)
        self.assertEqual(self.reload(notification).push_lease_token, current.lease_token)

        sent = PushAttemptResult(
            notification_id=notification.pk,
            status=Notification.PushStatus.SENT,
            attempts=1,
            delivered_device_ids=["device-id"],
            sent_at=timezone.now(),
        )
        self.assertEqual(record_results([sent], lease_token=current.lease_token)["sent"], 1)
        with self.assertLogs("notifications.push_worker", level="WARNING"):
            self.assertEqual(record_results([retry], lease_token=stale.lease_token)["lease_lost"], 1)

        row = self.reload(notification)
        self.assertEqual(row.push_status, Notification.PushStatus.SENT)
        self.assertEqual(row.push_delivered_device_ids, ["device-id"])
        self.assertEqual(row.push_last_error, "")

    def test_skipped_when_disabled_at_send_time_or_no_devices(self, _app):
        self.device(self.guardian)
        with_device = self.notify(self.guardian, "With device")

        with override_settings(FIREBASE_PUSH_ENABLED=False):
            summary, send_each = self.run_batch()
        self.assertEqual(summary.skipped, 1)
        self.assertEqual(self.reload(with_device).push_status, Notification.PushStatus.SKIPPED)
        send_each.assert_not_called()

        without_devices = self.notify(self.make_guardian("worker-no-devices"), "No devices")
        summary, send_each = self.run_batch()
        self.assertEqual(summary.skipped, 1)
        self.assertEqual(self.reload(without_devices).push_status, Notification.PushStatus.SKIPPED)
        send_each.assert_not_called()

    def test_skipped_when_recipient_inactive_or_must_change_password(self, _app):
        for field, value in (("is_active", False), ("must_change_password", True)):
            with self.subTest(field=field):
                guardian = self.make_guardian(f"worker-{field}")
                self.device(guardian)
                notification = self.notify(guardian)
                User.objects.filter(pk=guardian.pk).update(**{field: value})

                _summary, send_each = self.run_batch()

                self.assertEqual(self.reload(notification).push_status, Notification.PushStatus.SKIPPED)
                send_each.assert_not_called()

    def test_firebase_initialization_failure_retries_the_batch(self, get_app):
        get_app.side_effect = RuntimeError("bad credentials")
        self.device(self.guardian)
        notification = self.notify(self.guardian)

        summary, send_each = self.run_batch()

        self.assertEqual(summary.retry, 1)
        row = self.reload(notification)
        self.assertEqual(row.push_status, Notification.PushStatus.PENDING)
        self.assertEqual(row.push_attempts, 1)
        self.assertEqual(row.push_last_error, "RuntimeError")
        self.assertNotIn("bad credentials", self.output)
        send_each.assert_not_called()

    def test_configuration_errors_are_logged_at_error_level(self, _app):
        for error in (
            messaging.ThirdPartyAuthError("apns"),
            firebase_exceptions.PermissionDeniedError("denied"),
            firebase_exceptions.UnauthenticatedError("unauthenticated"),
        ):
            with self.subTest(error=type(error).__name__):
                device = self.device(self.make_guardian(f"worker-{type(error).__name__}"))
                notification = self.notify(device.user)

                self.run_batch({device.fcm_token: error})

                self.assertIn("ERROR:notifications.push_services:", self.output)
                self.assertIn(f"error={type(error).__name__}", self.output)
                self.assertNotIn(device.fcm_token, self.output)
                self.assertEqual(self.reload(notification).push_status, Notification.PushStatus.PENDING)


@override_settings(PUSH_WORKER_BATCH_SIZE=50, PUSH_WORKER_POLL_SECONDS=3)
@patch("notifications.push_worker.close_old_connections")
class PushWorkerLoopTests(SimpleTestCase):
    def run_worker(self, worker, *, batches, stop_after_waits):
        waits = []

        def wait(timeout):
            waits.append(timeout)
            if len(waits) >= stop_after_waits:
                worker.stop()
            return worker._stop.is_set()

        with patch.object(worker._stop, "wait", side_effect=wait), patch(
            "notifications.push_worker.process_batch", side_effect=batches,
        ) as process:
            worker.run()
        return waits, process

    def test_stop_finishes_the_current_batch_and_exits(self, _close):
        worker = PushWorker()

        def batch():
            worker.stop()
            return BatchSummary(claimed=50)

        with self.assertLogs("notifications.push_worker", level="INFO"):
            waits, process = self.run_worker(worker, batches=batch, stop_after_waits=99)
        self.assertEqual(process.call_count, 1)
        self.assertEqual(waits, [])

    def test_full_batch_runs_again_at_once_and_idle_batch_sleeps(self, _close):
        worker = PushWorker()
        with self.assertLogs("notifications.push_worker", level="INFO"):
            waits, process = self.run_worker(
                worker,
                batches=[BatchSummary(claimed=50), BatchSummary(claimed=3)],
                stop_after_waits=1,
            )
        self.assertEqual(process.call_count, 2)
        self.assertEqual(waits, [3])

    def test_errors_back_off_up_to_a_minute_without_crashing(self, close_connections):
        worker = PushWorker()
        with self.assertLogs("notifications.push_worker", level="INFO") as logs:
            waits, process = self.run_worker(
                worker,
                batches=DatabaseError("password=secret"),
                stop_after_waits=7,
            )
        self.assertEqual(waits, [3, 6, 12, 24, 48, 60, 60])
        self.assertEqual(process.call_count, 7)
        self.assertEqual(close_connections.call_count, 7)
        output = "\n".join(logs.output)
        self.assertIn("error=DatabaseError", output)
        self.assertNotIn("secret", output)

    def test_success_resets_the_error_backoff(self, _close):
        worker = PushWorker()
        with self.assertLogs("notifications.push_worker", level="INFO"):
            waits, _process = self.run_worker(
                worker,
                batches=[DatabaseError(), DatabaseError(), BatchSummary(), DatabaseError()],
                stop_after_waits=4,
            )
        self.assertEqual(waits, [3, 6, 3, 3])

    @patch("notifications.push_worker.PushWorker.run")
    @patch("notifications.management.commands.run_push_worker.signal.signal")
    def test_command_stops_cleanly_on_sigterm_and_sigint(self, install_handler, run, _close):
        import signal

        call_command("run_push_worker")

        run.assert_called_once_with()
        handled = {call.args[0]: call.args[1] for call in install_handler.call_args_list}
        self.assertEqual(set(handled), {signal.SIGTERM, signal.SIGINT})
        worker = handled[signal.SIGTERM].__self__
        self.assertIsInstance(worker, PushWorker)
        self.assertEqual(handled[signal.SIGINT], handled[signal.SIGTERM])


@PUSH_SETTINGS
class PushQueueStatusCommandTests(PushWorkerFixture, TestCase):
    def setUp(self):
        self.guardian = self.make_guardian()

    def status(self, *args):
        output = StringIO()
        call_command("push_queue_status", *args, stdout=output)
        return output.getvalue()

    def test_counts_by_status_and_ok_without_pending(self):
        sent = self.notify(self.guardian, "Sent")
        Notification.objects.filter(pk=sent.pk).update(push_status=Notification.PushStatus.SENT)

        output = self.status()

        self.assertIn("sent: 1", output)
        self.assertIn("pending: 0", output)
        self.assertIn("oldest_due_overdue_seconds: -", output)

    def test_recently_due_pending_is_ok(self):
        notification = self.notify(self.guardian)
        Notification.objects.filter(pk=notification.pk).update(
            push_next_attempt_at=timezone.now() - timedelta(seconds=10)
        )
        self.assertIn("pending: 1", self.status())

    def test_old_pending_waiting_for_a_retry_is_ok(self):
        notification = self.notify(self.guardian)
        Notification.objects.filter(pk=notification.pk).update(
            created_at=timezone.now() - timedelta(hours=1),
            push_next_attempt_at=timezone.now() + timedelta(minutes=30),
        )
        self.assertIn("pending: 1", self.status())

    def test_stuck_due_pending_exits_non_zero(self):
        notification = self.notify(self.guardian)
        Notification.objects.filter(pk=notification.pk).update(
            push_next_attempt_at=timezone.now() - timedelta(minutes=10)
        )

        with self.assertRaises(CommandError) as raised:
            self.status()
        self.assertEqual(raised.exception.returncode, 1)
        self.assertIn("run_push_worker", str(raised.exception))

        self.status("--max-age-seconds", "900")


@skipUnless(connection.vendor == "postgresql", "يتطلب PostgreSQL حقيقيًا")
@PUSH_SETTINGS
class PushWorkerPostgreSQLConcurrencyTests(PushWorkerFixture, TransactionTestCase):
    reset_sequences = True

    def in_thread(self, function):
        def run():
            connections.close_all()
            try:
                return function()
            finally:
                connections.close_all()

        return run

    def test_two_workers_never_send_the_same_notification(self):
        guardian = self.make_guardian()
        notifications = [self.notify(guardian, f"Concurrent {index}") for index in range(4)]
        sent_ids = []
        both_sending = Barrier(2, timeout=10)

        def fake_send(claimed):
            ids = [notification.id for notification in claimed]
            sent_ids.extend(ids)
            # Both workers are mid-send together, so neither lease has ended.
            both_sending.wait()
            return [
                PushAttemptResult(
                    notification_id=notification_id,
                    status=Notification.PushStatus.SENT,
                    attempts=1,
                    delivered_device_ids=[],
                    sent_at=timezone.now(),
                )
                for notification_id in ids
            ]

        with override_settings(PUSH_WORKER_BATCH_SIZE=2), patch(
            "notifications.push_worker.send_claimed_notifications", side_effect=fake_send,
        ), self.assertLogs("notifications.push_worker", level="INFO"):
            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(self.in_thread(process_batch))
                second = executor.submit(self.in_thread(process_batch))
                summaries = [first.result(timeout=20), second.result(timeout=20)]

        self.assertEqual([summary.claimed for summary in summaries], [2, 2])
        self.assertEqual(len(sent_ids), 4)
        self.assertEqual(set(sent_ids), {notification.id for notification in notifications})
        self.assertEqual(
            set(Notification.objects.values_list("push_status", flat=True)),
            {Notification.PushStatus.SENT},
        )

    def test_claim_skips_rows_locked_by_another_open_claim(self):
        guardian = self.make_guardian()
        locked, free = self.notify(guardian, "Locked"), self.notify(guardian, "Free")
        Notification.objects.filter(pk=locked.pk).update(
            created_at=timezone.now() - timedelta(minutes=5)
        )

        def claim_ids():
            return [notification.pk for notification in claim_batch().notifications]

        with transaction.atomic():
            list(Notification.objects.select_for_update().filter(pk=locked.pk))
            with ThreadPoolExecutor(max_workers=1) as executor:
                claimed = executor.submit(self.in_thread(claim_ids)).result(timeout=10)

        self.assertEqual(claimed, [free.pk])
