from datetime import timedelta

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class AnnouncementPublishNotifiedMigrationTests(TransactionTestCase):
    migrate_from = ("announcements", "0001_initial")
    migrate_to = ("announcements", "0002_announcement_publish_notified_at")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        # Keep every other app at its latest state; otherwise the historical
        # User model comes from accounts' first migration only.
        targets = [
            node for node in executor.loader.graph.leaf_nodes()
            if node[0] != "announcements"
        ] + [self.migrate_from]
        executor.migrate(targets)
        old_apps = executor.loader.project_state(targets).apps
        User = old_apps.get_model("accounts", "User")
        Announcement = old_apps.get_model("announcements", "Announcement")

        admin_pk = User.objects.create(
            username="announcement-migration-admin",
            role="school_admin",
        ).pk
        today = timezone.localdate()

        def announcement(title, publish_date):
            return Announcement.objects.create(
                scope="all",
                title=title,
                content="Content",
                publish_date=publish_date,
                created_by_id=admin_pk,
            )

        self.past = announcement("Past", today - timedelta(days=30))
        self.today = announcement("Today", today)
        self.future = announcement("Future", today + timedelta(days=1))

        targets = targets[:-1] + [self.migrate_to]
        self.before_migration = timezone.now()
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        self.after_migration = timezone.now()
        self.apps = executor.loader.project_state(targets).apps

    def tearDown(self):
        MigrationExecutor(connection).migrate(
            MigrationExecutor(connection).loader.graph.leaf_nodes()
        )
        super().tearDown()

    def test_published_announcements_are_marked_and_future_ones_stay_due(self):
        Announcement = self.apps.get_model("announcements", "Announcement")

        for old in (self.past, self.today):
            with self.subTest(title=old.title):
                migrated = Announcement.objects.get(pk=old.pk)
                self.assertIsNotNone(migrated.publish_notified_at)
                self.assertGreaterEqual(migrated.publish_notified_at, self.before_migration)
                self.assertLessEqual(migrated.publish_notified_at, self.after_migration)
                # The mark is a plain UPDATE; it does not touch updated_at.
                self.assertEqual(migrated.updated_at, old.updated_at)

        self.assertIsNone(
            Announcement.objects.get(pk=self.future.pk).publish_notified_at
        )

    def test_due_index_exists(self):
        Announcement = self.apps.get_model("announcements", "Announcement")
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(
                cursor, Announcement._meta.db_table,
            )
        self.assertIn("announce_notify_due_idx", constraints)
        self.assertEqual(
            constraints["announce_notify_due_idx"]["columns"], ["publish_date"]
        )
