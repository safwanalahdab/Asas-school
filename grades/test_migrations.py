from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.models.signals import post_save
from django.test import TransactionTestCase
from django.contrib.auth import get_user_model

from accounts.signals import apply_role_permission_template_on_user_creation


class PublishedGradeCorrectionPermissionMigrationTests(TransactionTestCase):
    migrate_from = ("grades", "0004_assessment_correct_published_grades")
    migrate_to = (
        "grades",
        "0005_backfill_published_grade_correction_permission",
    )

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        User = get_user_model()
        ContentType = old_apps.get_model("contenttypes", "ContentType")
        Permission = old_apps.get_model("auth", "Permission")

        content_type, _ = ContentType.objects.get_or_create(
            app_label="grades", model="assessment",
        )
        Permission.objects.filter(
            content_type=content_type,
            codename="correct_published_grades",
        ).delete()
        post_save.disconnect(
            apply_role_permission_template_on_user_creation,
            sender=User,
        )
        try:
            self.user_ids = {
                role: User.objects.create(username=f"existing-{role}", role=role).pk
                for role in ("school_admin", "supervisor", "teacher", "accountant", "secretariat")
            }
        finally:
            post_save.connect(
                apply_role_permission_template_on_user_creation,
                sender=User,
            )

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.apps = executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self):
        MigrationExecutor(connection).migrate(
            MigrationExecutor(connection).loader.graph.leaf_nodes()
        )
        super().tearDown()

    def test_permission_is_granted_only_to_existing_admins_and_supervisors(self):
        User = self.apps.get_model("accounts", "User")
        Permission = self.apps.get_model("auth", "Permission")
        permission = Permission.objects.get(
            content_type__app_label="grades",
            content_type__model="assessment",
            codename="correct_published_grades",
        )

        granted_roles = {
            role for role, user_id in self.user_ids.items()
            if User.objects.get(pk=user_id).user_permissions.filter(pk=permission.pk).exists()
        }
        self.assertEqual(granted_roles, {"school_admin", "supervisor"})
