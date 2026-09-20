from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from academics.models import GradeLevel, SupervisorScope, SupervisorScopeStage
from academics.supervisor_scope_services import set_supervisor_scope


User = get_user_model()


class SupervisorScopeModelTests(TestCase):
    def setUp(self):
        self.supervisor = User.objects.create_user(
            username="scope-model-supervisor",
            role=User.Role.SUPERVISOR,
        )
        self.scope = SupervisorScope.objects.create(
            supervisor=self.supervisor,
            scope_type=SupervisorScope.ScopeType.SELECTED_STAGES,
        )

    def test_supervisor_is_one_to_one(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            SupervisorScope.objects.create(
                supervisor=self.supervisor,
                scope_type=SupervisorScope.ScopeType.ALL,
            )

    def test_duplicate_stage_is_rejected_by_database(self):
        SupervisorScopeStage.objects.create(
            scope=self.scope,
            stage=GradeLevel.Stage.PRIMARY,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            SupervisorScopeStage.objects.create(
                scope=self.scope,
                stage=GradeLevel.Stage.PRIMARY,
            )

    def test_invalid_stage_is_rejected_by_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            SupervisorScopeStage.objects.create(
                scope=self.scope,
                stage="invalid-stage",
            )


class SupervisorScopeServiceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="scope-admin",
            role=User.Role.SCHOOL_ADMIN,
        )
        self.supervisor = User.objects.create_user(
            username="scope-supervisor",
            role=User.Role.SUPERVISOR,
        )

    def set_scope(self, scope_type, stages, actor=None, supervisor=None):
        return set_supervisor_scope(
            supervisor=supervisor or self.supervisor,
            scope_type=scope_type,
            stages=stages,
            actor=actor or self.admin,
        )

    def test_all_requires_empty_stages(self):
        with self.assertRaises(ValidationError):
            self.set_scope(
                SupervisorScope.ScopeType.ALL,
                [GradeLevel.Stage.PRIMARY],
            )

    def test_selected_stages_requires_at_least_one_stage(self):
        with self.assertRaises(ValidationError):
            self.set_scope(SupervisorScope.ScopeType.SELECTED_STAGES, [])

    def test_invalid_and_duplicate_stages_are_rejected(self):
        with self.assertRaises(ValidationError):
            self.set_scope(SupervisorScope.ScopeType.SELECTED_STAGES, ["invalid"])
        with self.assertRaises(ValidationError):
            self.set_scope(
                SupervisorScope.ScopeType.SELECTED_STAGES,
                [GradeLevel.Stage.PRIMARY, GradeLevel.Stage.PRIMARY],
            )

    def test_non_supervisor_cannot_have_scope(self):
        teacher = User.objects.create_user(
            username="scope-teacher",
            role=User.Role.TEACHER,
        )
        with self.assertRaises(ValidationError):
            self.set_scope(SupervisorScope.ScopeType.ALL, [], supervisor=teacher)

    def test_only_admin_or_superuser_can_update_scope(self):
        teacher = User.objects.create_user(
            username="scope-actor-teacher",
            role=User.Role.TEACHER,
        )
        with self.assertRaises(PermissionDenied):
            self.set_scope(SupervisorScope.ScopeType.ALL, [], actor=teacher)

        root = User.objects.create_superuser(
            username="scope-root",
            password="RootStrong!934",
        )
        scope = self.set_scope(SupervisorScope.ScopeType.ALL, [], actor=root)
        self.assertEqual(scope.scope_type, SupervisorScope.ScopeType.ALL)

    def test_switching_scope_type_replaces_stages_atomically(self):
        scope = self.set_scope(
            SupervisorScope.ScopeType.SELECTED_STAGES,
            [GradeLevel.Stage.PRIMARY, GradeLevel.Stage.SECONDARY],
        )
        self.assertEqual(
            set(scope.stages.values_list("stage", flat=True)),
            {GradeLevel.Stage.PRIMARY, GradeLevel.Stage.SECONDARY},
        )

        scope = self.set_scope(SupervisorScope.ScopeType.ALL, [])
        self.assertEqual(scope.scope_type, SupervisorScope.ScopeType.ALL)
        self.assertFalse(scope.stages.exists())

        scope = self.set_scope(
            SupervisorScope.ScopeType.SELECTED_STAGES,
            [GradeLevel.Stage.PREPARATORY],
        )
        self.assertEqual(
            list(scope.stages.values_list("stage", flat=True)),
            [GradeLevel.Stage.PREPARATORY],
        )


class SupervisorScopeDataMigrationTests(TransactionTestCase):
    migrate_from = (
        "academics",
        "0004_supervisorscope_supervisorscopestage_and_more",
    )
    migrate_to = ("academics", "0005_backfill_supervisor_scopes")
    accounts_migration = ("accounts", "0008_alter_user_role")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        before_targets = [self.migrate_from, self.accounts_migration]
        executor.migrate(before_targets)
        old_apps = executor.loader.project_state(before_targets).apps
        OldUser = old_apps.get_model("accounts", "User")
        self.supervisor_id = OldUser.objects.create(
            username="existing-migration-supervisor",
            role="supervisor",
        ).pk
        self.teacher_id = OldUser.objects.create(
            username="existing-migration-teacher",
            role="teacher",
        ).pk

        executor = MigrationExecutor(connection)
        after_targets = [self.migrate_to, self.accounts_migration]
        executor.migrate(after_targets)
        self.apps = executor.loader.project_state(after_targets).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_existing_supervisors_receive_all_scope_without_user_changes(self):
        HistoricalUser = self.apps.get_model("accounts", "User")
        HistoricalScope = self.apps.get_model("academics", "SupervisorScope")
        HistoricalStage = self.apps.get_model("academics", "SupervisorScopeStage")

        supervisor = HistoricalUser.objects.get(pk=self.supervisor_id)
        teacher = HistoricalUser.objects.get(pk=self.teacher_id)
        scope = HistoricalScope.objects.get(supervisor_id=self.supervisor_id)

        self.assertEqual(supervisor.username, "existing-migration-supervisor")
        self.assertEqual(supervisor.role, "supervisor")
        self.assertEqual(teacher.username, "existing-migration-teacher")
        self.assertEqual(teacher.role, "teacher")
        self.assertEqual(scope.scope_type, "all")
        self.assertFalse(HistoricalStage.objects.filter(scope=scope).exists())
        self.assertFalse(HistoricalScope.objects.filter(supervisor_id=self.teacher_id).exists())
