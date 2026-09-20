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
)
from students.models import Enrollment, Student
from teaching.models import TeacherAssignment


class SupervisorStudentScopeApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.old_year = AcademicYear.objects.create(
            start_date=date(2025, 9, 1),
            end_date=date(2026, 6, 30),
            status=AcademicYear.Status.CLOSED,
        )
        cls.active_year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )
        cls.primary = GradeLevel.objects.create(stage="primary", name="Primary")
        cls.preparatory = GradeLevel.objects.create(
            stage="preparatory", name="Preparatory"
        )
        cls.secondary = GradeLevel.objects.create(stage="secondary", name="Secondary")
        cls.old_primary = cls.section(cls.old_year, cls.primary, "Old Primary")
        cls.old_secondary = cls.section(cls.old_year, cls.secondary, "Old Secondary")
        cls.active_primary = cls.section(cls.active_year, cls.primary, "Primary A")
        cls.active_preparatory = cls.section(
            cls.active_year, cls.preparatory, "Preparatory A"
        )
        cls.active_secondary = cls.section(
            cls.active_year, cls.secondary, "Secondary A"
        )

        cls.current_primary = cls.student("Current Primary")
        cls.enroll(cls.current_primary, cls.active_year, cls.active_primary)
        cls.current_preparatory = cls.student("Current Preparatory")
        cls.enroll(
            cls.current_preparatory, cls.active_year, cls.active_preparatory
        )
        cls.current_secondary = cls.student("Current Secondary")
        cls.enroll(cls.current_secondary, cls.active_year, cls.active_secondary)

        cls.old_primary_current_preparatory = cls.student("Moved Up")
        cls.old_primary_enrollment = cls.enroll(
            cls.old_primary_current_preparatory, cls.old_year, cls.old_primary
        )
        cls.enroll(
            cls.old_primary_current_preparatory,
            cls.active_year,
            cls.active_preparatory,
        )
        cls.old_secondary_current_primary = cls.student("Moved In")
        cls.enroll(
            cls.old_secondary_current_primary, cls.old_year, cls.old_secondary
        )
        cls.enroll(
            cls.old_secondary_current_primary, cls.active_year, cls.active_primary
        )
        cls.unenrolled = cls.student("Unenrolled")
        cls.inactive_primary = cls.student("Inactive Primary", is_active=False)
        cls.enroll(cls.inactive_primary, cls.active_year, cls.active_primary)

        cls.all_supervisor = cls.user("student-all", User.Role.SUPERVISOR)
        SupervisorScope.objects.create(
            supervisor=cls.all_supervisor, scope_type=SupervisorScope.ScopeType.ALL
        )
        cls.primary_supervisor = cls.scoped_supervisor(
            "student-primary", ["primary"]
        )
        cls.preparatory_supervisor = cls.scoped_supervisor(
            "student-preparatory", ["preparatory"]
        )
        cls.multi_supervisor = cls.scoped_supervisor(
            "student-multi", ["primary", "preparatory"]
        )
        cls.missing_supervisor = cls.user("student-missing", User.Role.SUPERVISOR)
        cls.admin = cls.user("student-admin", User.Role.SCHOOL_ADMIN)
        cls.secretariat = cls.user("student-secretariat", User.Role.SECRETARIAT)
        cls.teacher = cls.user("student-teacher", User.Role.TEACHER)
        cls.accountant = cls.user("student-accountant", User.Role.ACCOUNTANT)
        cls.root = User.objects.create_superuser(
            username="student-root", password="x", must_change_password=False
        )

        permissions = list(Permission.objects.filter(content_type__app_label="students"))
        for user in (
            cls.all_supervisor,
            cls.primary_supervisor,
            cls.preparatory_supervisor,
            cls.multi_supervisor,
            cls.missing_supervisor,
            cls.admin,
            cls.secretariat,
        ):
            user.user_permissions.add(*permissions)

        subject = Subject.objects.create(name="Teacher Subject")
        plan = GradeSubject.objects.create(
            academic_year=cls.active_year,
            grade_level=cls.primary,
            subject=subject,
        )
        TeacherAssignment.objects.create(
            teacher=cls.teacher,
            grade_subject=plan,
            section=cls.active_primary,
            start_date=date(2026, 9, 1),
        )
        cls.teacher.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="students", codename="view_student"
            )
        )

    @classmethod
    def section(cls, year, grade, name):
        return Section.objects.create(
            academic_year=year, grade_level=grade, name=name
        )

    @classmethod
    def student(cls, first_name, *, is_active=True):
        return Student.objects.create(
            first_name=first_name,
            last_name="Student",
            birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
            is_active=is_active,
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

    def ids(self, response):
        return {row["id"] for row in self.rows(response)}

    def test_selected_scope_uses_only_active_year_enrollment(self):
        response = self.client_for(self.primary_supervisor).get(
            "/api/v1/students/students/"
        )
        self.assertEqual(response.status_code, 200)
        ids = self.ids(response)
        self.assertIn(str(self.current_primary.pk), ids)
        self.assertIn(str(self.old_secondary_current_primary.pk), ids)
        self.assertIn(str(self.inactive_primary.pk), ids)
        self.assertNotIn(str(self.old_primary_current_preparatory.pk), ids)
        self.assertNotIn(str(self.unenrolled.pk), ids)

    def test_historical_enrollment_does_not_grant_student_access_but_remains_visible(self):
        client = self.client_for(self.primary_supervisor)
        student_url = (
            f"/api/v1/students/students/{self.old_primary_current_preparatory.pk}/"
        )
        enrollment_url = (
            f"/api/v1/students/enrollments/{self.old_primary_enrollment.pk}/"
        )
        self.assertEqual(client.get(student_url).status_code, 404)
        self.assertEqual(client.get(enrollment_url).status_code, 200)

    def test_retrieve_patch_activate_deactivate_and_delete_use_scoped_object(self):
        client = self.client_for(self.primary_supervisor)
        inside_url = f"/api/v1/students/students/{self.current_primary.pk}/"
        outside_url = f"/api/v1/students/students/{self.current_secondary.pk}/"
        self.assertEqual(client.get(inside_url).status_code, 200)
        self.assertEqual(
            client.patch(inside_url, {"mother_name": "Updated"}, format="json").status_code,
            200,
        )
        self.assertEqual(
            client.post(f"{inside_url}deactivate/", {}, format="json").status_code,
            200,
        )
        self.assertIn(
            str(self.current_primary.pk),
            self.ids(client.get("/api/v1/students/students/")),
        )
        self.assertEqual(
            client.post(f"{inside_url}activate/", {}, format="json").status_code,
            200,
        )
        for method, suffix, body in (
            (client.get, "", None),
            (client.patch, "", {"mother_name": "Blocked"}),
            (client.post, "activate/", {}),
            (client.post, "deactivate/", {}),
            (client.delete, "", None),
        ):
            with self.subTest(operation=suffix or method.__name__):
                url = f"{outside_url}{suffix}"
                response = method(url, body, format="json") if body is not None else method(url)
                self.assertEqual(response.status_code, 404)

        self.assertEqual(client.delete(inside_url).status_code, 400)

    def test_create_is_allowed_but_created_student_is_not_owned(self):
        client = self.client_for(self.primary_supervisor)
        created = client.post(
            "/api/v1/students/students/",
            {
                "first_name": "Created",
                "last_name": "Without Enrollment",
                "birth_date": "2016-01-01",
                "gender": Student.Gender.FEMALE,
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        student_id = created.data["data"]["id"]
        self.assertNotIn(
            student_id, self.ids(client.get("/api/v1/students/students/"))
        )
        self.assertEqual(
            client.get(f"/api/v1/students/students/{student_id}/").status_code,
            404,
        )
        self.assertEqual(
            client.patch(
                f"/api/v1/students/students/{student_id}/",
                {"first_name": "Blocked"},
                format="json",
            ).status_code,
            404,
        )

    def test_multi_all_and_missing_scope(self):
        multi_ids = self.ids(
            self.client_for(self.multi_supervisor).get(
                "/api/v1/students/students/"
            )
        )
        self.assertIn(str(self.current_primary.pk), multi_ids)
        self.assertIn(str(self.current_preparatory.pk), multi_ids)
        self.assertNotIn(str(self.current_secondary.pk), multi_ids)

        all_ids = self.ids(
            self.client_for(self.all_supervisor).get("/api/v1/students/students/")
        )
        self.assertIn(str(self.current_secondary.pk), all_ids)
        self.assertIn(str(self.unenrolled.pk), all_ids)

        missing_client = self.client_for(self.missing_supervisor)
        self.assertEqual(
            self.rows(missing_client.get("/api/v1/students/students/")), []
        )
        self.assertEqual(
            missing_client.get(
                f"/api/v1/students/students/{self.current_primary.pk}/"
            ).status_code,
            404,
        )
        created = missing_client.post(
            "/api/v1/students/students/",
            {
                "first_name": "Missing",
                "last_name": "Scope",
                "birth_date": "2016-01-01",
                "gender": Student.Gender.MALE,
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(
            missing_client.get(
                f"/api/v1/students/students/{created.data['data']['id']}/"
            ).status_code,
            404,
        )

    def test_no_active_year_fails_closed_only_for_selected_scope(self):
        self.active_year.status = AcademicYear.Status.CLOSED
        self.active_year.save(update_fields=["status"])
        selected = self.client_for(self.primary_supervisor).get(
            "/api/v1/students/students/"
        )
        self.assertEqual(self.rows(selected), [])
        all_response = self.client_for(self.all_supervisor).get(
            "/api/v1/students/students/"
        )
        self.assertIn(str(self.unenrolled.pk), self.ids(all_response))

    def test_search_and_filters_cannot_expand_scope(self):
        client = self.client_for(self.primary_supervisor)
        allowed_ids = {
            str(self.current_primary.pk),
            str(self.old_secondary_current_primary.pk),
            str(self.inactive_primary.pk),
        }
        for params in (
            {"search": "Current Secondary"},
            {"section": str(self.active_secondary.pk)},
            {"grade_level": str(self.secondary.pk)},
            {"academic_year": str(self.old_year.pk), "grade_level": str(self.primary.pk)},
            {"is_active": "false", "section": str(self.active_secondary.pk)},
        ):
            with self.subTest(params=params):
                response = client.get("/api/v1/students/students/", params)
                result_ids = self.ids(response)
                self.assertTrue(result_ids.issubset(allowed_ids))
                self.assertNotIn(str(self.current_secondary.pk), result_ids)

    def test_business_permission_is_required_inside_scope(self):
        permission = Permission.objects.get(
            content_type__app_label="students", codename="change_student"
        )
        self.primary_supervisor.user_permissions.remove(permission)
        url = f"/api/v1/students/students/{self.current_primary.pk}/"
        self.assertEqual(
            self.client_for(self.primary_supervisor).patch(
                url, {"mother_name": "Denied"}, format="json"
            ).status_code,
            403,
        )

    def test_teacher_assignment_scope_is_preserved(self):
        response = self.client_for(self.teacher).get("/api/v1/students/students/")
        self.assertEqual(response.status_code, 200)
        ids = self.ids(response)
        self.assertIn(str(self.current_primary.pk), ids)
        self.assertNotIn(str(self.current_secondary.pk), ids)

    def test_admin_superuser_secretariat_unchanged_and_accountant_not_granted(self):
        for user in (self.admin, self.secretariat, self.root):
            with self.subTest(role=user.role):
                response = self.client_for(user).get("/api/v1/students/students/")
                self.assertEqual(response.status_code, 200)
                self.assertIn(str(self.unenrolled.pk), self.ids(response))

        self.assertEqual(
            self.client_for(self.accountant)
            .get("/api/v1/students/students/")
            .status_code,
            403,
        )
