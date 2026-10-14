import uuid

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


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
        # The columns code from before the outbox writes on every insert.
        self.pre_outbox_fields = list(Notification._meta.concrete_fields)

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

    def test_insert_without_push_columns_is_skipped(self):
        """Code from before the outbox (e.g. after a rollback) can still insert."""
        Notification = self.apps.get_model("notifications", "Notification")
        notification_id = uuid.uuid4()
        now = timezone.now()
        values = {
            "id": notification_id,
            "recipient": self.guardian_pk,
            "notification_type": "general",
            "title": "Pre-outbox code",
            "body": "Body",
            "student": None,
            "resource_type": "",
            "resource_id": None,
            "event_key": None,
            "is_read": False,
            "read_at": None,
            "created_at": now,
            "updated_at": now,
        }
        self.assertEqual({field.name for field in self.pre_outbox_fields}, set(values))
        quote = connection.ops.quote_name
        columns = ", ".join(quote(field.column) for field in self.pre_outbox_fields)
        placeholders = ", ".join(["%s"] * len(self.pre_outbox_fields))
        params = [
            field.get_db_prep_value(values[field.name], connection)
            for field in self.pre_outbox_fields
        ]
        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {quote(Notification._meta.db_table)} ({columns}) "
                f"VALUES ({placeholders})",
                params,
            )

        row = Notification.objects.get(pk=notification_id)
        self.assertEqual(row.push_status, "skipped")
        self.assertEqual(row.push_attempts, 0)
        self.assertEqual(row.push_last_error, "")
        self.assertEqual(row.push_delivered_device_ids, [])
        self.assertIsNone(row.push_next_attempt_at)
        self.assertIsNone(row.push_lease_token)
