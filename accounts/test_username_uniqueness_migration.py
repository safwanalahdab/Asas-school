from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

CONSTRAINT_NAME = "unique_user_username_case_insensitive"


class UsernameCaseInsensitiveMigrationTests(TransactionTestCase):
    migrate_from = ("accounts", "0010_user_created_by")
    migrate_to = ("accounts", "0011_user_unique_user_username_case_insensitive")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        # Keep every other app at its latest state.
        self.targets = [
            node for node in executor.loader.graph.leaf_nodes()
            if node[0] != "accounts"
        ] + [self.migrate_from]
        executor.migrate(self.targets)
        self.old_apps = executor.loader.project_state(self.targets).apps
        self.OldUser = self.old_apps.get_model("accounts", "User")
        self.duplicate_ids = []

    def tearDown(self):
        # Case duplicates would stop the latest migration from re-applying.
        self.OldUser.objects.filter(pk__in=self.duplicate_ids).delete()
        MigrationExecutor(connection).migrate(
            MigrationExecutor(connection).loader.graph.leaf_nodes()
        )
        super().tearDown()

    def make_user(self, username):
        return self.OldUser.objects.create(username=username, role="teacher")

    def migrate_forward(self):
        targets = self.targets[:-1] + [self.migrate_to]
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def constraint_names(self):
        with connection.cursor() as cursor:
            return set(
                connection.introspection.get_constraints(cursor, "accounts_user")
            )

    def test_migration_adds_constraint_when_usernames_are_unique(self):
        ahmad = self.make_user("Ahmad")
        self.make_user("other-user")

        new_apps = self.migrate_forward()

        self.assertIn(CONSTRAINT_NAME, self.constraint_names())
        User = new_apps.get_model("accounts", "User")
        self.assertEqual(User.objects.get(pk=ahmad.pk).username, "Ahmad")
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create(username="AHMAD", role="teacher")

    def test_existing_duplicates_stop_migration_without_changing_accounts(self):
        groups = [
            [self.make_user("Ahmad"), self.make_user("ahmad")],
            [self.make_user("Sara"), self.make_user("SARA"), self.make_user("sara")],
        ]
        untouched = self.make_user("unique-user")
        self.duplicate_ids = [user.pk for group in groups for user in group]
        before = sorted(self.OldUser.objects.values_list("pk", "username"))

        with self.assertRaises(RuntimeError) as caught:
            self.migrate_forward()

        message = str(caught.exception)
        self.assertIn("found 2 group(s)", message)
        self.assertIn("Resolve them manually", message)
        for group in groups:
            ids = ", ".join(sorted(str(user.pk) for user in group))
            self.assertIn(f"[{ids}]", message)
        self.assertNotIn(str(untouched.pk), message)
        for username in ("Ahmad", "ahmad", "Sara", "SARA", "sara", "unique-user"):
            self.assertNotIn(username, message)

        self.assertEqual(
            sorted(self.OldUser.objects.values_list("pk", "username")), before
        )
        self.assertNotIn(CONSTRAINT_NAME, self.constraint_names())
        recorded = MigrationExecutor(connection).loader.applied_migrations
        self.assertNotIn(self.migrate_to, recorded)
