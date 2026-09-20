from datetime import date

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from academics.models import (
    AcademicYear,
    GradeLevel,
    GradeSubject,
    Section,
    Subject,
    SupervisorScope,
    SupervisorScopeStage,
    Term,
)


class SupervisorAcademicScopeApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )
        cls.primary = GradeLevel.objects.create(stage="primary", name="Primary One")
        cls.term = Term.objects.create(
            academic_year=cls.year,
            number=Term.Number.FIRST,
            start_date=date(2026, 9, 1),
            end_date=date(2027, 1, 31),
        )
        cls.preparatory = GradeLevel.objects.create(
            stage="preparatory", name="Preparatory One"
        )
        cls.secondary = GradeLevel.objects.create(
            stage="secondary", name="Secondary One"
        )
        cls.primary_section = Section.objects.create(
            academic_year=cls.year, grade_level=cls.primary, name="Primary A"
        )
        cls.preparatory_section = Section.objects.create(
            academic_year=cls.year,
            grade_level=cls.preparatory,
            name="Preparatory A",
        )
        cls.secondary_section = Section.objects.create(
            academic_year=cls.year, grade_level=cls.secondary, name="Secondary A"
        )
        cls.primary_subject = Subject.objects.create(name="Primary Subject")
        cls.secondary_subject = Subject.objects.create(name="Secondary Subject")
        cls.primary_plan = GradeSubject.objects.create(
            academic_year=cls.year,
            grade_level=cls.primary,
            subject=cls.primary_subject,
        )
        cls.secondary_plan = GradeSubject.objects.create(
            academic_year=cls.year,
            grade_level=cls.secondary,
            subject=cls.secondary_subject,
        )

        cls.all_supervisor = cls.make_user("academic-all", User.Role.SUPERVISOR)
        SupervisorScope.objects.create(
            supervisor=cls.all_supervisor, scope_type=SupervisorScope.ScopeType.ALL
        )
        cls.primary_supervisor = cls.scoped_supervisor(
            "academic-primary", ["primary"]
        )
        cls.multi_supervisor = cls.scoped_supervisor(
            "academic-multi", ["primary", "preparatory"]
        )
        cls.missing_supervisor = cls.make_user(
            "academic-missing", User.Role.SUPERVISOR
        )
        cls.admin = cls.make_user("academic-admin", User.Role.SCHOOL_ADMIN)
        cls.secretariat = cls.make_user(
            "academic-secretariat", User.Role.SECRETARIAT
        )
        cls.teacher = cls.make_user("academic-teacher", User.Role.TEACHER)
        cls.guardian = cls.make_user("academic-guardian", User.Role.GUARDIAN)
        cls.accountant = cls.make_user("academic-accountant", User.Role.ACCOUNTANT)
        cls.tech = cls.make_user("academic-tech", User.Role.TECH_SUPPORT)
        cls.root = User.objects.create_superuser(
            username="academic-root", password="x", must_change_password=False
        )

        cls.academic_permissions = list(
            Permission.objects.filter(content_type__app_label="academics")
        )
        for user in (
            cls.all_supervisor,
            cls.primary_supervisor,
            cls.multi_supervisor,
            cls.missing_supervisor,
            cls.admin,
            cls.secretariat,
        ):
            user.user_permissions.add(*cls.academic_permissions)

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

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user, token={"client": "web"})
        return client

    @staticmethod
    def rows(response):
        data = response.data["data"]
        return data.get("results", data) if isinstance(data, dict) else data

    def ids(self, response):
        return {row["id"] for row in self.rows(response)}

    def test_selected_stage_filters_grade_levels_and_blocks_direct_uuid(self):
        client = self.client_for(self.primary_supervisor)
        response = client.get("/api/v1/academics/grade-levels/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.ids(response), {str(self.primary.pk)})
        self.assertEqual(
            client.get(
                f"/api/v1/academics/grade-levels/{self.secondary.pk}/"
            ).status_code,
            404,
        )
        self.assertEqual(
            client.delete(
                f"/api/v1/academics/grade-levels/{self.secondary.pk}/"
            ).status_code,
            404,
        )

    def test_selected_stage_grade_level_create_patch_and_delete(self):
        client = self.client_for(self.primary_supervisor)
        allowed = client.post(
            "/api/v1/academics/grade-levels/",
            {"stage": "primary", "name": "Primary Disposable"},
            format="json",
        )
        self.assertEqual(allowed.status_code, 201)
        grade_id = allowed.data["data"]["id"]
        self.assertEqual(
            client.patch(
                f"/api/v1/academics/grade-levels/{grade_id}/",
                {"name": "Primary Updated"},
                format="json",
            ).status_code,
            200,
        )
        self.assertEqual(
            client.post(
                "/api/v1/academics/grade-levels/",
                {"stage": "secondary", "name": "Forbidden Secondary"},
                format="json",
            ).status_code,
            403,
        )
        self.assertEqual(
            client.patch(
                f"/api/v1/academics/grade-levels/{grade_id}/",
                {"stage": "preparatory"},
                format="json",
            ).status_code,
            403,
        )
        self.assertEqual(
            client.delete(
                f"/api/v1/academics/grade-levels/{grade_id}/"
            ).status_code,
            200,
        )

    def test_multi_stage_cannot_move_grade_level_between_allowed_stages(self):
        client = self.client_for(self.multi_supervisor)
        self.assertEqual(
            self.ids(client.get("/api/v1/academics/grade-levels/")),
            {str(self.primary.pk), str(self.preparatory.pk)},
        )
        response = client.patch(
            f"/api/v1/academics/grade-levels/{self.primary.pk}/",
            {"stage": "preparatory"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_section_scope_and_foreign_key_injection(self):
        client = self.client_for(self.primary_supervisor)
        response = client.get("/api/v1/academics/sections/")
        self.assertEqual(self.ids(response), {str(self.primary_section.pk)})
        self.assertEqual(
            client.get(
                f"/api/v1/academics/sections/{self.secondary_section.pk}/"
            ).status_code,
            404,
        )
        self.assertEqual(
            client.post(
                "/api/v1/academics/sections/",
                {
                    "academic_year": str(self.year.pk),
                    "grade_level": str(self.secondary.pk),
                    "name": "Injected",
                },
                format="json",
            ).status_code,
            403,
        )
        self.assertEqual(
            client.patch(
                f"/api/v1/academics/sections/{self.primary_section.pk}/",
                {"grade_level": str(self.secondary.pk)},
                format="json",
            ).status_code,
            403,
        )

    def test_grade_subject_scope_and_foreign_key_injection(self):
        client = self.client_for(self.primary_supervisor)
        response = client.get("/api/v1/academics/grade-subjects/")
        self.assertEqual(self.ids(response), {str(self.primary_plan.pk)})
        self.assertEqual(
            client.get(
                f"/api/v1/academics/grade-subjects/{self.secondary_plan.pk}/"
            ).status_code,
            404,
        )
        self.assertEqual(
            client.post(
                "/api/v1/academics/grade-subjects/",
                {
                    "academic_year": str(self.year.pk),
                    "grade_level": str(self.secondary.pk),
                    "subject": str(self.primary_subject.pk),
                },
                format="json",
            ).status_code,
            403,
        )
        self.assertEqual(
            client.patch(
                f"/api/v1/academics/grade-subjects/{self.primary_plan.pk}/",
                {"grade_level": str(self.secondary.pk)},
                format="json",
            ).status_code,
            403,
        )

    def test_selected_and_missing_scope_read_but_cannot_write_global_resources(self):
        resources = (
            ("academic-years", self.year.pk),
            ("terms", self.term.pk),
            ("subjects", self.primary_subject.pk),
        )
        for user in (self.primary_supervisor, self.missing_supervisor):
            client = self.client_for(user)
            for route, object_id in resources:
                with self.subTest(user=user.username, route=route):
                    base = f"/api/v1/academics/{route}/"
                    self.assertEqual(client.get(base).status_code, 200)
                    self.assertEqual(client.get(f"{base}{object_id}/").status_code, 200)
                    self.assertEqual(client.post(base, {}, format="json").status_code, 403)
                    self.assertEqual(
                        client.patch(f"{base}{object_id}/", {}, format="json").status_code,
                        403,
                    )
                    self.assertEqual(client.delete(f"{base}{object_id}/").status_code, 403)

    def test_missing_scope_fails_closed_for_stage_resources(self):
        client = self.client_for(self.missing_supervisor)
        for route in ("grade-levels", "sections", "grade-subjects"):
            with self.subTest(route=route):
                response = client.get(f"/api/v1/academics/{route}/")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.rows(response), [])
        self.assertEqual(
            client.get(
                f"/api/v1/academics/grade-levels/{self.primary.pk}/"
            ).status_code,
            404,
        )
        self.assertEqual(
            client.post(
                "/api/v1/academics/grade-levels/",
                {"stage": "primary", "name": "Missing Scope"},
                format="json",
            ).status_code,
            403,
        )

    def test_all_scope_preserves_read_and_write_behavior(self):
        client = self.client_for(self.all_supervisor)
        self.assertEqual(
            self.ids(client.get("/api/v1/academics/grade-levels/")),
            {str(self.primary.pk), str(self.preparatory.pk), str(self.secondary.pk)},
        )
        created = client.post(
            "/api/v1/academics/subjects/",
            {"name": "All Scope Subject"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        subject_id = created.data["data"]["id"]
        self.assertEqual(
            client.patch(
                f"/api/v1/academics/subjects/{subject_id}/",
                {"name": "All Scope Updated"},
                format="json",
            ).status_code,
            200,
        )
        self.assertEqual(
            client.delete(f"/api/v1/academics/subjects/{subject_id}/").status_code,
            200,
        )

    def test_business_permission_is_still_required_inside_scope(self):
        permission = Permission.objects.get(
            content_type__app_label="academics", codename="view_gradelevel"
        )
        self.primary_supervisor.user_permissions.remove(permission)
        self.assertEqual(
            self.client_for(self.primary_supervisor)
            .get("/api/v1/academics/grade-levels/")
            .status_code,
            403,
        )

    def test_other_roles_and_superuser_are_not_scope_limited(self):
        for user in (self.admin, self.secretariat, self.root):
            with self.subTest(role=user.role):
                response = self.client_for(user).get(
                    "/api/v1/academics/grade-levels/"
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(str(self.secondary.pk), self.ids(response))

        add_subject = Permission.objects.get(
            content_type__app_label="academics", codename="add_subject"
        )
        self.teacher.user_permissions.add(add_subject)
        response = self.client_for(self.teacher).post(
            "/api/v1/academics/subjects/",
            {"name": "Direct Permission Subject"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

        view_grade_level = Permission.objects.get(
            content_type__app_label="academics", codename="view_gradelevel"
        )
        for user in (self.guardian, self.accountant, self.tech):
            with self.subTest(direct_permission_role=user.role):
                user.user_permissions.add(view_grade_level)
                response = self.client_for(user).get(
                    "/api/v1/academics/grade-levels/"
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(str(self.secondary.pk), self.ids(response))

    def test_search_and_filters_cannot_expand_selected_scope(self):
        client = self.client_for(self.primary_supervisor)
        grade_response = client.get(
            "/api/v1/academics/grade-levels/", {"search": "Secondary"}
        )
        self.assertEqual(self.rows(grade_response), [])
        section_response = client.get(
            "/api/v1/academics/sections/",
            {"grade_level": str(self.secondary.pk), "search": "Secondary"},
        )
        self.assertEqual(self.rows(section_response), [])
        plan_response = client.get(
            "/api/v1/academics/grade-subjects/",
            {"grade_level": str(self.secondary.pk)},
        )
        self.assertEqual(self.rows(plan_response), [])
