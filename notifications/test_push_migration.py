from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class NotificationPushOutboxMigrationTests(TransactionTestCase):
    migrate_from = ("notifications", "0002_pushdevice")
    migrate_to = ("notifications", "0003_notification_push_outbox")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        # Keep every other app at its latest state; otherwise the historical
        # User model comes from accounts' first migration only.
        targets = [
            node for node in executor.loader.graph.leaf_nodes()
            if node[0] != "notifications"
        ] + [self.migrate_from]
        executor.migrate(targets)
        old_apps = executor.loader.project_state(targets).apps
        User = old_apps.get_model("accounts", "User")
        Notification = old_apps.get_model("notifications", "Notification")

        self.guardian_pk = User.objects.create(
            username="push-migration-guardian",
            role="guardian",
        ).pk
        self.existing_notification_ids = [
            Notification.objects.create(
                recipient_id=self.guardian_pk,
                notification_type="general",
                title=f"Existing {index}",
                body="Body",
            ).pk
            for index in range(2)
        ]

        targets = targets[:-1] + [self.migrate_to]
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        self.apps = executor.loader.project_state(targets).apps

    def tearDown(self):
        MigrationExecutor(connection).migrate(
            MigrationExecutor(connection).loader.graph.leaf_nodes()
        )
        super().tearDown()

    def test_existing_notifications_are_skipped_and_new_ones_are_pending(self):
        Notification = self.apps.get_model("notifications", "Notification")

        existing = Notification.objects.filter(pk__in=self.existing_notification_ids)
        self.assertEqual(existing.count(), 2)
        for notification in existing:
            with self.subTest(notification=notification.pk):
                self.assertEqual(notification.push_status, "skipped")
                self.assertEqual(notification.push_attempts, 0)
                self.assertIsNone(notification.push_locked_until)
                self.assertIsNone(notification.push_lease_token)
                self.assertIsNone(notification.push_sent_at)
                self.assertEqual(notification.push_last_error, "")
                self.assertEqual(notification.push_delivered_device_ids, [])

        created = Notification.objects.create(
            recipient_id=self.guardian_pk,
            notification_type="general",
            title="New",
            body="Body",
        )
        created.refresh_from_db()
        self.assertEqual(created.push_status, "pending")
        self.assertEqual(created.push_attempts, 0)
        self.assertIsNotNone(created.push_next_attempt_at)
        self.assertEqual(created.push_delivered_device_ids, [])
