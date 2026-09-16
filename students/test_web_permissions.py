from datetime import date

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, GradeSubject, Section, Subject
from accounts.models import User
from teaching.models import TeacherAssignment

from .models import Enrollment, GuardianStudent, Student
from .services import ensure_student_health_profile


class StudentsBusinessPermissionTests(TestCase):
    def setUp(self):
        self.year = AcademicYear.objects.create(
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
        )
        self.grade = GradeLevel.objects.create(stage="primary", name="الأول")
        self.assigned = Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name="أ"
        )
        self.unassigned = Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name="ب"
        )
        subject = Subject.objects.create(name="الرياضيات")
        plan = GradeSubject.objects.create(
            academic_year=self.year, grade_level=self.grade, subject=subject
        )
        self.admin = self.make_user("students-auth-admin", User.Role.SCHOOL_ADMIN)
        self.teacher = self.make_user("students-auth-teacher", User.Role.TEACHER)
        self.tech = self.make_user("students-auth-tech", User.Role.TECH_SUPPORT)
        self.guardian = self.make_user("students-auth-guardian", User.Role.GUARDIAN)
        self.root = User.objects.create_superuser(
            username="students-auth-root", password="x", must_change_password=False
        )
        for user in (self.admin, self.teacher, self.tech, self.guardian):
            user.user_permissions.clear()
        TeacherAssignment.objects.create(
            teacher=self.teacher, grade_subject=plan, section=self.assigned,
            start_date=date(2026, 1, 1),
        )
        self.in_scope, self.in_enrollment = self.make_student("داخل", self.assigned)
        self.out_scope, self.out_enrollment = self.make_student("خارج", self.unassigned)
        ensure_student_health_profile(self.in_scope)
        self.link = GuardianStudent.objects.create(
            guardian=self.guardian, student=self.in_scope
        )

    def make_user(self, username, role):
        return User.objects.create_user(
            username=username, password="x", role=role, must_change_password=False
        )

    def make_student(self, first_name, section):
        student = Student.objects.create(
            first_name=first_name, last_name="طالب", birth_date=date(2018, 1, 1), gender="male"
        )
        enrollment = Enrollment.objects.create(
            student=student, academic_year=self.year, section=section,
            enrollment_date=date(2026, 1, 1),
        )
        return student, enrollment

    def grant(self, user, *codes):
        user.user_permissions.add(*[
            Permission.objects.get(
                content_type__app_label=code.split(".", 1)[0],
                codename=code.split(".", 1)[1],
            )
            for code in codes
        ])

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user, token={"client": "web"})
        return client

    @staticmethod
    def rows(response):
        payload = response.data["data"]
        return payload.get("results", payload) if isinstance(payload, dict) else payload

    def test_school_admin_without_view_student_is_forbidden(self):
        self.assertEqual(
            self.client_for(self.admin).get("/api/v1/students/students/").status_code,
            403,
        )

    def test_teacher_student_and_enrollment_scope_is_preserved(self):
        self.grant(self.teacher, "students.view_student", "students.view_enrollment")
        client = self.client_for(self.teacher)
        students = client.get("/api/v1/students/students/")
        self.assertEqual(students.status_code, 200)
        self.assertEqual(
            {item["id"] for item in self.rows(students)}, {str(self.in_scope.id)}
        )
        enrollments = client.get("/api/v1/students/enrollments/")
        self.assertEqual(
            {item["id"] for item in self.rows(enrollments)},
            {str(self.in_enrollment.id)},
        )
        self.assertEqual(
            client.get(f"/api/v1/students/students/{self.out_scope.id}/").status_code,
            404,
        )

    def test_nontraditional_role_with_view_permission_is_allowed(self):
        self.grant(self.tech, "students.view_student")
        response = self.client_for(self.tech).get("/api/v1/students/students/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.rows(response)), 2)

    def test_student_crud_permissions_are_independent(self):
        client = self.client_for(self.admin)
        self.grant(self.admin, "students.add_student")
        self.assertEqual(
            client.post("/api/v1/students/students/", {}, format="json").status_code,
            400,
        )
        self.assertEqual(
            client.get("/api/v1/students/students/").status_code, 403
        )
        self.admin.user_permissions.clear()
        self.grant(self.admin, "students.change_student")
        self.assertEqual(
            client.patch(
                f"/api/v1/students/students/{self.in_scope.id}/",
                {"first_name": "معدل"}, format="json",
            ).status_code,
            200,
        )
        self.admin.user_permissions.clear()
        self.grant(self.admin, "students.delete_student")
        disposable = Student.objects.create(
            first_name="حذف", last_name="طالب", birth_date=date(2018, 1, 1), gender="male"
        )
        self.assertEqual(
            client.delete(f"/api/v1/students/students/{disposable.id}/").status_code,
            200,
        )

    def test_registration_and_transfer_permissions_are_independent(self):
        client = self.client_for(self.admin)
        self.assertEqual(
            client.post("/api/v1/students/register/", {}, format="json").status_code,
            403,
        )
        self.grant(self.admin, "students.register_student")
        self.assertEqual(
            client.post("/api/v1/students/register/", {}, format="json").status_code,
            400,
        )
        self.admin.user_permissions.clear()
        self.assertEqual(
            client.post(
                f"/api/v1/students/enrollments/{self.in_enrollment.id}/transfer/",
                {}, format="json",
            ).status_code,
            403,
        )
        self.grant(self.admin, "students.transfer_student")
        self.assertEqual(
            client.post(
                f"/api/v1/students/enrollments/{self.in_enrollment.id}/transfer/",
                {}, format="json",
            ).status_code,
            400,
        )

    def test_health_profile_permissions_are_independent(self):
        client = self.client_for(self.admin)
        self.grant(self.admin, "students.view_studenthealthprofile")
        url = f"/api/v1/students/{self.in_scope.id}/health-profile/"
        self.assertEqual(client.get(url).status_code, 200)
        self.assertEqual(client.patch(url, {}, format="json").status_code, 403)
        self.admin.user_permissions.clear()
        self.grant(self.admin, "students.change_studenthealthprofile")
        self.assertEqual(client.patch(url, {}, format="json").status_code, 200)
        self.assertEqual(client.get(url).status_code, 403)

    def test_health_profile_head_uses_get_permission(self):
        client = self.client_for(self.admin)
        url = f"/api/v1/students/{self.in_scope.id}/health-profile/"
        self.assertEqual(client.head(url).status_code, 403)
        self.grant(self.admin, "students.view_studenthealthprofile")
        self.assertEqual(client.head(url).status_code, 200)

    def test_health_profile_options_skips_only_business_permission(self):
        url = f"/api/v1/students/{self.in_scope.id}/health-profile/"
        self.assertEqual(self.client_for(self.admin).options(url).status_code, 200)

        anonymous = APIClient()
        self.assertEqual(anonymous.options(url).status_code, 401)

        mobile = APIClient()
        mobile.force_authenticate(user=self.admin, token={"client": "mobile"})
        self.assertEqual(mobile.options(url).status_code, 403)

    def test_health_profile_unsupported_method_reaches_405(self):
        client = self.client_for(self.admin)
        url = f"/api/v1/students/{self.in_scope.id}/health-profile/"
        self.assertEqual(client.post(url, {}, format="json").status_code, 405)

    def test_guardian_link_permissions_are_independent(self):
        client = self.client_for(self.admin)
        url = "/api/v1/students/guardian-links/"
        self.grant(self.admin, "students.view_guardianstudent")
        self.assertEqual(client.get(url).status_code, 200)
        self.assertEqual(client.post(url, {}, format="json").status_code, 403)
        self.assertEqual(
            client.delete(f"{url}{self.link.id}/").status_code, 403
        )
        self.admin.user_permissions.clear()
        self.grant(self.admin, "students.add_guardianstudent")
        self.assertEqual(client.post(url, {}, format="json").status_code, 400)
        self.admin.user_permissions.clear()
        self.grant(self.admin, "students.delete_guardianstudent")
        self.assertEqual(client.delete(f"{url}{self.link.id}/").status_code, 200)

    def test_superuser_bypasses_direct_permissions(self):
        self.assertEqual(
            self.client_for(self.root).get("/api/v1/students/students/").status_code,
            200,
        )
