from datetime import date

from django.test import TestCase

from accounts.models import User
from academics.models import (
    AcademicYear,
    GradeLevel,
    Section,
    SupervisorScope,
    SupervisorScopeStage,
)
from academics.supervisor_academic_scope import (
    can_access_enrollment,
    can_access_grade_level,
    can_access_section,
    can_access_student,
    can_change_grade_level_stage,
    can_manage_global_academic_resources,
    filter_enrollments_by_supervisor_scope,
    filter_queryset_by_stage,
    filter_students_by_supervisor_scope,
    is_stage_allowed,
    is_stage_scoped_supervisor,
    supervisor_academic_scope_for,
)
from students.models import Enrollment, Student


class SupervisorAcademicScopePolicyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.active_year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )
        cls.old_year = AcademicYear.objects.create(
            start_date=date(2025, 9, 1),
            end_date=date(2026, 6, 30),
            status=AcademicYear.Status.CLOSED,
        )
        cls.primary = GradeLevel.objects.create(stage="primary", name="Primary")
        cls.preparatory = GradeLevel.objects.create(
            stage="preparatory", name="Preparatory"
        )
        cls.secondary = GradeLevel.objects.create(stage="secondary", name="Secondary")
        cls.primary_old = Section.objects.create(
            academic_year=cls.old_year, grade_level=cls.primary, name="Old Primary"
        )
        cls.primary_active = Section.objects.create(
            academic_year=cls.active_year, grade_level=cls.primary, name="Primary A"
        )
        cls.preparatory_active = Section.objects.create(
            academic_year=cls.active_year,
            grade_level=cls.preparatory,
            name="Preparatory A",
        )
        cls.secondary_active = Section.objects.create(
            academic_year=cls.active_year,
            grade_level=cls.secondary,
            name="Secondary A",
        )

        cls.current_primary = cls.make_student("Current", "Primary")
        cls.current_preparatory = cls.make_student("Current", "Preparatory")
        cls.old_primary_current_preparatory = cls.make_student("Moved", "Student")
        cls.without_enrollment = cls.make_student("No", "Enrollment")
        cls.primary_enrollment = cls.enroll(
            cls.current_primary, cls.active_year, cls.primary_active
        )
        cls.preparatory_enrollment = cls.enroll(
            cls.current_preparatory, cls.active_year, cls.preparatory_active
        )
        cls.old_primary_enrollment = cls.enroll(
            cls.old_primary_current_preparatory, cls.old_year, cls.primary_old
        )
        cls.enroll(
            cls.old_primary_current_preparatory,
            cls.active_year,
            cls.preparatory_active,
        )

        cls.admin = cls.make_user("scope-admin", User.Role.SCHOOL_ADMIN)
        cls.teacher = cls.make_user("scope-teacher", User.Role.TEACHER)
        cls.accountant = cls.make_user("scope-accountant", User.Role.ACCOUNTANT)
        cls.root = User.objects.create_superuser(
            username="scope-root", password="x", must_change_password=False
        )
        cls.all_supervisor = cls.make_user("scope-all", User.Role.SUPERVISOR)
        SupervisorScope.objects.create(
            supervisor=cls.all_supervisor, scope_type=SupervisorScope.ScopeType.ALL
        )
        cls.primary_supervisor = cls.scoped_supervisor(
            "scope-primary", ["primary"]
        )
        cls.multi_supervisor = cls.scoped_supervisor(
            "scope-multi", ["primary", "preparatory"]
        )
        cls.missing_scope_supervisor = cls.make_user(
            "scope-missing", User.Role.SUPERVISOR
        )

    @classmethod
    def make_user(cls, username, role):
        return User.objects.create_user(
            username=username,
            password="x",
            role=role,
            must_change_password=False,
        )

    @classmethod
    def scoped_supervisor(cls, username, stages):
        user = cls.make_user(username, User.Role.SUPERVISOR)
        scope = SupervisorScope.objects.create(
            supervisor=user,
            scope_type=SupervisorScope.ScopeType.SELECTED_STAGES,
        )
        SupervisorScopeStage.objects.bulk_create(
            [SupervisorScopeStage(scope=scope, stage=stage) for stage in stages]
        )
        return user

    @classmethod
    def make_student(cls, first_name, last_name):
        return Student.objects.create(
            first_name=first_name,
            last_name=last_name,
            birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )

    @classmethod
    def enroll(cls, student, year, section):
        return Enrollment.objects.create(
            student=student,
            academic_year=year,
            section=section,
            enrollment_date=year.start_date,
        )

    def ids(self, queryset):
        return set(queryset.values_list("pk", flat=True))

    def test_scope_state_all_selected_multiple_and_missing(self):
        self.assertTrue(is_stage_scoped_supervisor(self.all_supervisor))
        self.assertTrue(supervisor_academic_scope_for(self.all_supervisor).allows_all_stages)
        self.assertEqual(
            supervisor_academic_scope_for(self.multi_supervisor).stages,
            frozenset({"primary", "preparatory"}),
        )
        missing = supervisor_academic_scope_for(self.missing_scope_supervisor)
        self.assertTrue(missing.applies)
        self.assertIsNone(missing.scope_type)

    def test_non_supervisors_and_superuser_are_unaffected(self):
        for user in (self.admin, self.teacher, self.accountant, self.root):
            with self.subTest(role=user.role):
                self.assertFalse(is_stage_scoped_supervisor(user))
                self.assertEqual(
                    self.ids(filter_queryset_by_stage(GradeLevel.objects.all(), user)),
                    self.ids(GradeLevel.objects.all()),
                )

    def test_direct_and_related_stage_querysets(self):
        self.assertEqual(
            self.ids(filter_queryset_by_stage(GradeLevel.objects.all(), self.primary_supervisor)),
            {self.primary.pk},
        )
        sections = filter_queryset_by_stage(
            Section.objects.all(),
            self.multi_supervisor,
            stage_lookup="grade_level__stage",
        )
        self.assertEqual(
            self.ids(sections),
            {self.primary_old.pk, self.primary_active.pk, self.preparatory_active.pk},
        )
        self.assertFalse(
            filter_queryset_by_stage(
                GradeLevel.objects.all(), self.missing_scope_supervisor
            ).exists()
        )

    def test_stage_and_fk_target_checks(self):
        self.assertTrue(is_stage_allowed(self.primary_supervisor, "primary"))
        self.assertFalse(is_stage_allowed(self.primary_supervisor, "secondary"))
        self.assertTrue(can_access_grade_level(self.primary_supervisor, self.primary))
        self.assertTrue(can_access_section(self.primary_supervisor, self.primary_active))
        self.assertFalse(
            can_access_section(self.primary_supervisor, self.preparatory_active)
        )
        self.assertTrue(
            can_access_enrollment(self.primary_supervisor, self.old_primary_enrollment)
        )

    def test_students_use_only_the_active_year_and_do_not_duplicate(self):
        scoped = filter_students_by_supervisor_scope(
            Student.objects.all(), self.primary_supervisor
        )
        self.assertEqual(self.ids(scoped), {self.current_primary.pk})
        self.assertEqual(scoped.count(), 1)
        self.assertFalse(
            can_access_student(
                self.primary_supervisor, self.old_primary_current_preparatory
            )
        )
        self.assertFalse(can_access_student(self.primary_supervisor, self.without_enrollment))

    def test_enrollments_keep_their_own_historical_stage(self):
        scoped = filter_enrollments_by_supervisor_scope(
            Enrollment.objects.all(), self.primary_supervisor
        )
        self.assertEqual(
            self.ids(scoped),
            {self.primary_enrollment.pk, self.old_primary_enrollment.pk},
        )

    def test_all_scope_keeps_students_without_enrollments_visible(self):
        self.assertEqual(
            self.ids(
                filter_students_by_supervisor_scope(
                    Student.objects.all(), self.all_supervisor
                )
            ),
            self.ids(Student.objects.all()),
        )

    def test_missing_scope_fails_closed_for_stage_resources(self):
        self.assertFalse(
            filter_students_by_supervisor_scope(
                Student.objects.all(), self.missing_scope_supervisor
            ).exists()
        )
        self.assertFalse(
            filter_enrollments_by_supervisor_scope(
                Enrollment.objects.all(), self.missing_scope_supervisor
            ).exists()
        )

    def test_no_active_year_does_not_fall_back_to_historical_enrollment(self):
        self.active_year.status = AcademicYear.Status.CLOSED
        self.active_year.save(update_fields=["status"])
        self.assertFalse(
            filter_students_by_supervisor_scope(
                Student.objects.all(), self.primary_supervisor
            ).exists()
        )

    def test_global_resource_and_grade_stage_write_policies(self):
        self.assertFalse(can_manage_global_academic_resources(self.primary_supervisor))
        self.assertFalse(
            can_manage_global_academic_resources(self.missing_scope_supervisor)
        )
        self.assertTrue(can_manage_global_academic_resources(self.all_supervisor))
        self.assertTrue(can_manage_global_academic_resources(self.admin))
        self.assertTrue(
            can_change_grade_level_stage(
                self.primary_supervisor, self.primary, "primary"
            )
        )
        self.assertFalse(
            can_change_grade_level_stage(
                self.multi_supervisor, self.primary, "preparatory"
            )
        )
        self.assertTrue(
            can_change_grade_level_stage(
                self.all_supervisor, self.primary, "secondary"
            )
        )
