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
from students.models import Enrollment, GuardianStudent, Student, StudentHealthProfile


class SupervisorRelatedStudentScopeApiTests(TestCase):
    links_url = "/api/v1/students/guardian-links/"

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
        cls.active_primary = cls.section(cls.active_year, cls.primary, "Primary A")
        cls.active_preparatory = cls.section(
            cls.active_year, cls.preparatory, "Preparatory A"
        )
        cls.active_secondary = cls.section(
            cls.active_year, cls.secondary, "Secondary A"
        )

        cls.inside = cls.student("Inside")
        cls.enroll(cls.inside, cls.active_year, cls.active_primary)
        cls.outside = cls.student("Outside")
        cls.enroll(cls.outside, cls.active_year, cls.active_secondary)
        cls.historical_only = cls.student("Historical")
        cls.enroll(cls.historical_only, cls.old_year, cls.old_primary)
        cls.enroll(cls.historical_only, cls.active_year, cls.active_preparatory)
        cls.preparatory_student = cls.student("Preparatory")
        cls.enroll(
            cls.preparatory_student, cls.active_year, cls.active_preparatory
        )
        cls.unenrolled = cls.student("Unenrolled")

        cls.inside_profile = StudentHealthProfile.objects.create(
            student=cls.inside, blood_type="O+", health_notes="inside"
        )
        cls.outside_profile = StudentHealthProfile.objects.create(
            student=cls.outside, blood_type="A+", health_notes="unchanged"
        )

        cls.inside_guardian = cls.user("inside-guardian", User.Role.GUARDIAN)
        cls.outside_guardian = cls.user("outside-guardian", User.Role.GUARDIAN)
        cls.historical_guardian = cls.user("history-guardian", User.Role.GUARDIAN)
        cls.inside_link = GuardianStudent.objects.create(
            guardian=cls.inside_guardian, student=cls.inside, relationship="parent"
        )
        cls.outside_link = GuardianStudent.objects.create(
            guardian=cls.outside_guardian, student=cls.outside, relationship="parent"
        )
        cls.historical_link = GuardianStudent.objects.create(
            guardian=cls.historical_guardian,
            student=cls.historical_only,
            relationship="parent",
        )

        cls.all_supervisor = cls.user("related-all", User.Role.SUPERVISOR)
        SupervisorScope.objects.create(
            supervisor=cls.all_supervisor, scope_type=SupervisorScope.ScopeType.ALL
        )
        cls.primary_supervisor = cls.scoped_supervisor(
            "related-primary", ["primary"]
        )
        cls.multi_supervisor = cls.scoped_supervisor(
            "related-multi", ["primary", "preparatory"]
        )
        cls.missing_supervisor = cls.user("related-missing", User.Role.SUPERVISOR)
        cls.admin = cls.user("related-admin", User.Role.SCHOOL_ADMIN)
        cls.secretariat = cls.user("related-secretariat", User.Role.SECRETARIAT)
        cls.accountant = cls.user("related-accountant", User.Role.ACCOUNTANT)
        cls.root = User.objects.create_superuser(
            username="related-root", password="x", must_change_password=False
        )

        permissions = list(Permission.objects.filter(content_type__app_label="students"))
        for user in (
            cls.all_supervisor,
            cls.primary_supervisor,
            cls.multi_supervisor,
            cls.missing_supervisor,
            cls.admin,
            cls.secretariat,
        ):
            user.user_permissions.add(*permissions)

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

    def health_url(self, student):
        return f"/api/v1/students/{student.pk}/health-profile/"

    def test_health_get_and_patch_inside_and_outside_scope(self):
        client = self.client_for(self.primary_supervisor)
        self.assertEqual(client.get(self.health_url(self.inside)).status_code, 200)
        self.assertEqual(
            client.patch(
                self.health_url(self.inside),
                {"health_notes": "updated"},
                format="json",
            ).status_code,
            200,
        )
        self.assertEqual(client.get(self.health_url(self.outside)).status_code, 404)
        self.assertEqual(
            client.patch(
                self.health_url(self.outside),
                {"health_notes": "forbidden"},
                format="json",
            ).status_code,
            404,
        )
        self.outside_profile.refresh_from_db()
        self.assertEqual(self.outside_profile.health_notes, "unchanged")

    def test_health_checks_scope_before_creating_missing_profile(self):
        outside_without_profile = self.student("No Profile Outside")
        self.enroll(
            outside_without_profile, self.active_year, self.active_secondary
        )
        client = self.client_for(self.primary_supervisor)
        self.assertEqual(
            client.get(self.health_url(outside_without_profile)).status_code, 404
        )
        self.assertFalse(
            StudentHealthProfile.objects.filter(student=outside_without_profile).exists()
        )
        self.assertEqual(client.get(self.health_url(self.unenrolled)).status_code, 404)
        self.assertFalse(
            StudentHealthProfile.objects.filter(student=self.unenrolled).exists()
        )

    def test_health_historical_multi_all_missing_and_no_active_year(self):
        primary = self.client_for(self.primary_supervisor)
        self.assertEqual(
            primary.get(self.health_url(self.historical_only)).status_code, 404
        )
        multi = self.client_for(self.multi_supervisor)
        self.assertEqual(
            multi.get(self.health_url(self.preparatory_student)).status_code, 200
        )
        all_client = self.client_for(self.all_supervisor)
        self.assertEqual(all_client.get(self.health_url(self.unenrolled)).status_code, 200)
        missing = self.client_for(self.missing_supervisor)
        self.assertEqual(missing.get(self.health_url(self.inside)).status_code, 404)

        self.active_year.status = AcademicYear.Status.CLOSED
        self.active_year.save(update_fields=["status"])
        self.assertEqual(primary.get(self.health_url(self.inside)).status_code, 404)

    def test_health_business_permission_is_still_required(self):
        permission = Permission.objects.get(
            content_type__app_label="students",
            codename="view_studenthealthprofile",
        )
        self.primary_supervisor.user_permissions.remove(permission)
        self.assertEqual(
            self.client_for(self.primary_supervisor)
            .get(self.health_url(self.inside))
            .status_code,
            403,
        )

    def test_guardian_links_list_retrieve_and_historical_scope(self):
        client = self.client_for(self.primary_supervisor)
        response = client.get(self.links_url)
        self.assertEqual(
            {row["id"] for row in self.rows(response)}, {str(self.inside_link.pk)}
        )
        self.assertEqual(
            client.get(f"{self.links_url}{self.inside_link.pk}/").status_code, 200
        )
        self.assertEqual(
            client.get(f"{self.links_url}{self.outside_link.pk}/").status_code, 404
        )
        self.assertEqual(
            client.get(f"{self.links_url}{self.historical_link.pk}/").status_code,
            404,
        )

    def test_guardian_link_create_checks_student_foreign_key(self):
        client = self.client_for(self.primary_supervisor)
        existing_outside = client.post(
            self.links_url,
            {
                "guardian": str(self.outside_guardian.pk),
                "student": str(self.outside.pk),
            },
            format="json",
        )
        self.assertEqual(existing_outside.status_code, 403)

        eligible = self.student("Eligible Link")
        self.enroll(eligible, self.active_year, self.active_primary)
        guardian = self.user("eligible-link-guardian", User.Role.GUARDIAN)
        allowed = client.post(
            self.links_url,
            {"guardian": str(guardian.pk), "student": str(eligible.pk)},
            format="json",
        )
        self.assertEqual(allowed.status_code, 201)

        outside_without_link = self.student("Outside Without Link")
        self.enroll(
            outside_without_link, self.active_year, self.active_secondary
        )
        for student, username in (
            (outside_without_link, "outside-link-new-guardian"),
            (self.unenrolled, "unenrolled-link-guardian"),
        ):
            with self.subTest(student=student.pk):
                new_guardian = self.user(username, User.Role.GUARDIAN)
                response = client.post(
                    self.links_url,
                    {
                        "guardian": str(new_guardian.pk),
                        "student": str(student.pk),
                    },
                    format="json",
                )
                self.assertEqual(response.status_code, 403)
                self.assertFalse(
                    GuardianStudent.objects.filter(
                        guardian=new_guardian, student=student
                    ).exists()
                )

    def test_guardian_link_delete_inside_and_outside_scope(self):
        inside_student = self.student("Delete Link Inside")
        self.enroll(inside_student, self.active_year, self.active_primary)
        inside_link = GuardianStudent.objects.create(
            guardian=self.user("delete-inside-guardian", User.Role.GUARDIAN),
            student=inside_student,
        )
        client = self.client_for(self.primary_supervisor)
        self.assertEqual(
            client.delete(f"{self.links_url}{inside_link.pk}/").status_code, 200
        )
        self.assertEqual(
            client.delete(f"{self.links_url}{self.outside_link.pk}/").status_code,
            404,
        )
        self.assertTrue(GuardianStudent.objects.filter(pk=self.outside_link.pk).exists())

    def test_guardian_search_and_filters_cannot_expand_scope(self):
        client = self.client_for(self.primary_supervisor)
        for params in (
            {"student": str(self.outside.pk)},
            {"guardian": str(self.outside_guardian.pk)},
            {"search": self.outside.first_name},
        ):
            with self.subTest(params=params):
                self.assertEqual(
                    self.rows(client.get(self.links_url, params)), []
                )

    def test_registration_exception_creates_new_records_but_no_later_access(self):
        client = self.client_for(self.primary_supervisor)
        response = client.post(
            "/api/v1/students/register/",
            {
                "student": {
                    "first_name": "Registered",
                    "last_name": "Student",
                    "birth_date": "2016-01-01",
                    "gender": Student.Gender.FEMALE,
                },
                "health_profile": {"blood_type": "AB+"},
                "guardian": {
                    "national_id": "9911223344",
                    "first_name": "New",
                    "last_name": "Guardian",
                    "relationship": "parent",
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        student = Student.objects.get(pk=response.data["data"]["student"]["id"])
        self.assertTrue(StudentHealthProfile.objects.filter(student=student).exists())
        self.assertTrue(GuardianStudent.objects.filter(student=student).exists())
        self.assertEqual(client.get(self.health_url(student)).status_code, 404)
        self.assertEqual(
            client.get(f"/api/v1/students/students/{student.pk}/").status_code, 404
        )
        link = GuardianStudent.objects.get(student=student)
        self.assertEqual(
            client.delete(f"{self.links_url}{link.pk}/").status_code, 404
        )

        self.enroll(student, self.active_year, self.active_primary)
        self.assertEqual(client.get(self.health_url(student)).status_code, 200)
        self.assertEqual(
            client.get(f"/api/v1/students/students/{student.pk}/").status_code, 200
        )

    def test_other_roles_unchanged_and_accountant_not_granted(self):
        for user in (self.admin, self.secretariat, self.root):
            with self.subTest(role=user.role):
                self.assertEqual(
                    self.client_for(user).get(self.health_url(self.unenrolled)).status_code,
                    200,
                )
        self.assertEqual(
            self.client_for(self.accountant).get(self.health_url(self.inside)).status_code,
            403,
        )
