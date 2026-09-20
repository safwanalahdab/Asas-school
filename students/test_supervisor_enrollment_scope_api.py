from datetime import date

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from academics.models import (
    AcademicYear,
    GradeLevel,
    Section,
    SupervisorScope,
    SupervisorScopeStage,
)
from students.models import Enrollment, Student


class SupervisorEnrollmentScopeApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.old_year = AcademicYear.objects.create(
            start_date=date(2024, 9, 1),
            end_date=date(2025, 6, 30),
            status=AcademicYear.Status.CLOSED,
        )
        cls.current_year = AcademicYear.objects.create(
            start_date=date(2025, 9, 1),
            end_date=date(2026, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )
        cls.next_year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            status=AcademicYear.Status.DRAFT,
        )
        cls.primary = GradeLevel.objects.create(stage="primary", name="Primary")
        cls.preparatory = GradeLevel.objects.create(
            stage="preparatory", name="Preparatory"
        )
        cls.secondary = GradeLevel.objects.create(stage="secondary", name="Secondary")

        cls.old_primary = cls.section(cls.old_year, cls.primary, "Old Primary")
        cls.old_secondary = cls.section(cls.old_year, cls.secondary, "Old Secondary")
        cls.current_primary_a = cls.section(
            cls.current_year, cls.primary, "Primary A"
        )
        cls.current_primary_b = cls.section(
            cls.current_year, cls.primary, "Primary B"
        )
        cls.current_preparatory = cls.section(
            cls.current_year, cls.preparatory, "Preparatory A"
        )
        cls.current_secondary = cls.section(
            cls.current_year, cls.secondary, "Secondary A"
        )
        cls.next_primary = cls.section(cls.next_year, cls.primary, "Next Primary")

        cls.historical_student = cls.student("Historical")
        cls.old_primary_enrollment = cls.enroll(
            cls.historical_student, cls.old_year, cls.old_primary
        )
        cls.current_preparatory_enrollment = cls.enroll(
            cls.historical_student, cls.current_year, cls.current_preparatory
        )
        cls.primary_student = cls.student("Primary")
        cls.primary_enrollment = cls.enroll(
            cls.primary_student, cls.current_year, cls.current_primary_a
        )
        cls.secondary_student = cls.student("Secondary")
        cls.secondary_enrollment = cls.enroll(
            cls.secondary_student, cls.current_year, cls.current_secondary
        )

        cls.all_supervisor = cls.user("enrollment-all", User.Role.SUPERVISOR)
        SupervisorScope.objects.create(
            supervisor=cls.all_supervisor, scope_type=SupervisorScope.ScopeType.ALL
        )
        cls.primary_supervisor = cls.scoped_supervisor(
            "enrollment-primary", ["primary"]
        )
        cls.multi_supervisor = cls.scoped_supervisor(
            "enrollment-multi", ["primary", "preparatory"]
        )
        cls.missing_supervisor = cls.user(
            "enrollment-missing", User.Role.SUPERVISOR
        )
        cls.admin = cls.user("enrollment-admin", User.Role.SCHOOL_ADMIN)
        cls.secretariat = cls.user("enrollment-secretariat", User.Role.SECRETARIAT)
        cls.tech = cls.user("enrollment-tech", User.Role.TECH_SUPPORT)
        cls.root = User.objects.create_superuser(
            username="enrollment-root", password="x", must_change_password=False
        )

        cls.student_permissions = list(
            Permission.objects.filter(content_type__app_label="students")
        )
        for user in (
            cls.all_supervisor,
            cls.primary_supervisor,
            cls.multi_supervisor,
            cls.missing_supervisor,
            cls.admin,
            cls.secretariat,
        ):
            user.user_permissions.add(*cls.student_permissions)

    @classmethod
    def section(cls, year, grade, name):
        return Section.objects.create(
            academic_year=year, grade_level=grade, name=name
        )

    @classmethod
    def student(cls, first_name):
        return Student.objects.create(
            first_name=first_name,
            last_name="Student",
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

    @classmethod
    def user(cls, username, role):
        return User.objects.create_user(
            username=username,
            password="x",
            role=role,
            must_change_password=False,
        )

    @classmethod
    def scoped_supervisor(cls, username, stages):
        user = cls.user(username, User.Role.SUPERVISOR)
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

    def enrollment_payload(self, student, year, section):
        return {
            "student": str(student.pk),
            "academic_year": str(year.pk),
            "section": str(section.pk),
            "enrollment_date": str(year.start_date),
        }

    def test_list_retrieve_and_direct_uuid_follow_enrollment_stage(self):
        client = self.client_for(self.primary_supervisor)
        response = client.get("/api/v1/students/enrollments/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {row["id"] for row in self.rows(response)},
            {str(self.old_primary_enrollment.pk), str(self.primary_enrollment.pk)},
        )
        self.assertEqual(
            client.get(
                f"/api/v1/students/enrollments/{self.old_primary_enrollment.pk}/"
            ).status_code,
            200,
        )
        self.assertEqual(
            client.get(
                f"/api/v1/students/enrollments/{self.current_preparatory_enrollment.pk}/"
            ).status_code,
            404,
        )

    def test_filters_cannot_expand_scope(self):
        client = self.client_for(self.primary_supervisor)
        for params in (
            {"section": str(self.current_secondary.pk)},
            {"grade_level": str(self.secondary.pk)},
            {"student": str(self.secondary_student.pk)},
            {"academic_year": str(self.current_year.pk), "grade_level": str(self.secondary.pk)},
        ):
            with self.subTest(params=params):
                response = client.get("/api/v1/students/enrollments/", params)
                self.assertEqual(self.rows(response), [])

    def test_create_checks_target_section_not_student_history(self):
        client = self.client_for(self.primary_supervisor)
        no_history = self.student("No History")
        created = client.post(
            "/api/v1/students/enrollments/",
            self.enrollment_payload(no_history, self.current_year, self.current_primary_a),
            format="json",
        )
        self.assertEqual(created.status_code, 201)

        old_outside = self.student("Old Outside")
        self.enroll(old_outside, self.old_year, self.old_secondary)
        created_after_outside_history = client.post(
            "/api/v1/students/enrollments/",
            self.enrollment_payload(old_outside, self.next_year, self.next_primary),
            format="json",
        )
        self.assertEqual(created_after_outside_history.status_code, 201)

    def test_create_rejects_out_of_scope_section_uuid(self):
        student = self.student("Rejected Create")
        response = self.client_for(self.primary_supervisor).post(
            "/api/v1/students/enrollments/",
            self.enrollment_payload(student, self.current_year, self.current_secondary),
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Enrollment.objects.filter(student=student).exists())

    def test_patch_requires_source_scope_and_preserves_protected_section_contract(self):
        client = self.client_for(self.primary_supervisor)
        allowed = client.patch(
            f"/api/v1/students/enrollments/{self.primary_enrollment.pk}/",
            {"usual_arrival_method": Enrollment.TransportationMethod.GUARDIAN},
            format="json",
        )
        self.assertEqual(allowed.status_code, 200)

        protected_section = client.patch(
            f"/api/v1/students/enrollments/{self.primary_enrollment.pk}/",
            {"section": str(self.current_secondary.pk)},
            format="json",
        )
        self.assertEqual(protected_section.status_code, 400)
        self.primary_enrollment.refresh_from_db()
        self.assertEqual(self.primary_enrollment.section_id, self.current_primary_a.pk)

        outside_source = client.patch(
            f"/api/v1/students/enrollments/{self.secondary_enrollment.pk}/",
            {"section": str(self.current_primary_a.pk)},
            format="json",
        )
        self.assertEqual(outside_source.status_code, 404)

    def test_delete_inside_and_outside_scope(self):
        inside_student = self.student("Delete Inside")
        inside = self.enroll(inside_student, self.next_year, self.next_primary)
        outside_student = self.student("Delete Outside")
        outside = self.enroll(outside_student, self.old_year, self.old_secondary)
        client = self.client_for(self.primary_supervisor)
        self.assertEqual(
            client.delete(f"/api/v1/students/enrollments/{inside.pk}/").status_code,
            200,
        )
        self.assertEqual(
            client.delete(f"/api/v1/students/enrollments/{outside.pk}/").status_code,
            404,
        )
        self.assertTrue(Enrollment.objects.filter(pk=outside.pk).exists())

    def test_transfer_checks_both_source_and_target_scope(self):
        client = self.client_for(self.primary_supervisor)
        inside_student = self.student("Transfer Inside")
        inside = self.enroll(inside_student, self.current_year, self.current_primary_a)
        success = client.post(
            f"/api/v1/students/enrollments/{inside.pk}/transfer/",
            {"section": str(self.current_primary_b.pk)},
            format="json",
        )
        self.assertEqual(success.status_code, 200)

        target_outside_student = self.student("Target Outside")
        target_outside = self.enroll(
            target_outside_student, self.current_year, self.current_primary_a
        )
        target_outside_response = client.post(
            f"/api/v1/students/enrollments/{target_outside.pk}/transfer/",
            {"section": str(self.current_secondary.pk)},
            format="json",
        )
        self.assertEqual(target_outside_response.status_code, 403)

        source_outside = client.post(
            f"/api/v1/students/enrollments/{self.secondary_enrollment.pk}/transfer/",
            {"section": str(self.current_primary_a.pk)},
            format="json",
        )
        self.assertEqual(source_outside.status_code, 404)

    def test_all_multi_and_missing_scope_states(self):
        all_response = self.client_for(self.all_supervisor).get(
            "/api/v1/students/enrollments/"
        )
        self.assertIn(
            str(self.secondary_enrollment.pk),
            {row["id"] for row in self.rows(all_response)},
        )
        multi_response = self.client_for(self.multi_supervisor).get(
            "/api/v1/students/enrollments/"
        )
        multi_ids = {row["id"] for row in self.rows(multi_response)}
        self.assertIn(str(self.primary_enrollment.pk), multi_ids)
        self.assertIn(str(self.current_preparatory_enrollment.pk), multi_ids)
        self.assertNotIn(str(self.secondary_enrollment.pk), multi_ids)

        missing_client = self.client_for(self.missing_supervisor)
        self.assertEqual(
            self.rows(missing_client.get("/api/v1/students/enrollments/")), []
        )
        self.assertEqual(
            missing_client.get(
                f"/api/v1/students/enrollments/{self.primary_enrollment.pk}/"
            ).status_code,
            404,
        )
        student = self.student("Missing Scope")
        self.assertEqual(
            missing_client.post(
                "/api/v1/students/enrollments/",
                self.enrollment_payload(student, self.current_year, self.current_primary_a),
                format="json",
            ).status_code,
            403,
        )

    def test_business_permission_remains_required(self):
        permission = Permission.objects.get(
            content_type__app_label="students", codename="view_enrollment"
        )
        self.primary_supervisor.user_permissions.remove(permission)
        self.assertEqual(
            self.client_for(self.primary_supervisor)
            .get("/api/v1/students/enrollments/")
            .status_code,
            403,
        )

    def test_non_supervisor_roles_and_direct_permissions_are_unchanged(self):
        for user in (self.admin, self.secretariat, self.root):
            with self.subTest(role=user.role):
                response = self.client_for(user).get(
                    "/api/v1/students/enrollments/"
                )
                self.assertIn(
                    str(self.secondary_enrollment.pk),
                    {row["id"] for row in self.rows(response)},
                )

        view_permission = Permission.objects.get(
            content_type__app_label="students", codename="view_enrollment"
        )
        self.tech.user_permissions.add(view_permission)
        response = self.client_for(self.tech).get("/api/v1/students/enrollments/")
        self.assertIn(
            str(self.secondary_enrollment.pk),
            {row["id"] for row in self.rows(response)},
        )
