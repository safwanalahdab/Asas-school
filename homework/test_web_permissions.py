from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, GradeSubject, Section, Subject
from teaching.models import TeacherAssignment

from .models import Homework


User = get_user_model()


class HomeworkWebPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.teacher = self.user("homework-teacher", User.Role.TEACHER)
        self.other_teacher = self.user("homework-other", User.Role.TEACHER)
        self.admin = self.user("homework-admin", User.Role.SCHOOL_ADMIN)
        self.teacher.user_permissions.clear()
        self.admin.user_permissions.clear()
        year = AcademicYear.objects.create(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="Homework grade")
        section = Section.objects.create(academic_year=year, grade_level=grade, name="A")
        subject = Subject.objects.create(name="Homework subject")
        grade_subject = GradeSubject.objects.create(academic_year=year, grade_level=grade, subject=subject)
        self.assignment = TeacherAssignment.objects.create(
            teacher=self.teacher, grade_subject=grade_subject, section=section,
            start_date=date(2026, 1, 1),
        )
        self.other_assignment = TeacherAssignment.objects.create(
            teacher=self.other_teacher, grade_subject=grade_subject, section=section,
            start_date=date(2026, 1, 1),
        )
        self.own = self.homework(self.assignment)
        self.other = self.homework(self.other_assignment)

    def user(self, name, role):
        return User.objects.create_user(username=name, password="StrongPass!123", role=role, must_change_password=False)

    def grant(self, user, code):
        app, codename = code.split(".")
        user.user_permissions.add(Permission.objects.get(content_type__app_label=app, codename=codename))

    def homework(self, assignment):
        return Homework.objects.create(
            teacher_assignment=assignment, title="Homework", description="Description",
            homework_date=date(2026, 2, 1), due_date=date(2026, 2, 2), created_by=self.admin,
        )

    def payload(self, assignment):
        return {
            "teacher_assignment": str(assignment.pk), "title": "New homework",
            "description": "Description", "homework_date": "2026-02-03", "due_date": "2026-02-04",
        }

    def dated_assignment(self, *, start_date, end_date=None):
        return TeacherAssignment.objects.create(
            teacher=self.teacher,
            grade_subject=self.assignment.grade_subject,
            section=self.assignment.section,
            start_date=start_date,
            end_date=end_date,
        )

    def authenticate_teacher_with_permissions(self, *codenames):
        for codename in codenames:
            self.grant(self.teacher, f"homework.{codename}")
        self.client.force_authenticate(
            self.teacher,
            token={"client": "web"},
        )

    def end_assignment_yesterday(self, assignment):
        today = timezone.localdate()
        assignment.start_date = today - timedelta(days=2)
        assignment.end_date = today - timedelta(days=1)
        assignment.save(update_fields=["start_date", "end_date"])

    def test_teacher_can_read_homework_for_ended_assignment(self):
        self.end_assignment_yesterday(self.assignment)
        self.authenticate_teacher_with_permissions("view_homework")

        response = self.client.get("/api/v1/homework/homeworks/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            str(self.own.pk),
            [item["id"] for item in response.data["data"]["results"]],
        )
        self.assertEqual(
            self.client.get(
                f"/api/v1/homework/homeworks/{self.own.pk}/"
            ).status_code,
            200,
        )

    def test_teacher_cannot_create_homework_for_ended_assignment(self):
        self.end_assignment_yesterday(self.assignment)
        self.authenticate_teacher_with_permissions("add_homework")
        count = Homework.objects.count()

        response = self.client.post(
            "/api/v1/homework/homeworks/",
            self.payload(self.assignment),
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "HOMEWORK_ASSIGNMENT_ENDED")
        self.assertEqual(Homework.objects.count(), count)

    def test_teacher_cannot_update_homework_for_ended_assignment(self):
        self.end_assignment_yesterday(self.assignment)
        self.authenticate_teacher_with_permissions("change_homework")

        response = self.client.patch(
            f"/api/v1/homework/homeworks/{self.own.pk}/",
            {"title": "Changed"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "HOMEWORK_ASSIGNMENT_ENDED")
        self.own.refresh_from_db()
        self.assertEqual(self.own.title, "Homework")

    def test_teacher_cannot_bypass_ended_assignment_update_by_reassignment(self):
        today = timezone.localdate()
        self.end_assignment_yesterday(self.assignment)
        active_assignment = self.dated_assignment(
            start_date=today - timedelta(days=1),
        )
        future_assignment = self.dated_assignment(
            start_date=today + timedelta(days=1),
        )
        self.authenticate_teacher_with_permissions("change_homework")

        for replacement in (active_assignment, future_assignment):
            with self.subTest(replacement=replacement.pk):
                response = self.client.patch(
                    f"/api/v1/homework/homeworks/{self.own.pk}/",
                    {"teacher_assignment": str(replacement.pk)},
                    format="json",
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(
                    response.data["code"],
                    "HOMEWORK_ASSIGNMENT_ENDED",
                )
                self.own.refresh_from_db()
                self.assertEqual(
                    self.own.teacher_assignment_id,
                    self.assignment.pk,
                )

    def test_teacher_cannot_delete_homework_for_ended_assignment(self):
        self.end_assignment_yesterday(self.assignment)
        self.authenticate_teacher_with_permissions("delete_homework")

        response = self.client.delete(
            f"/api/v1/homework/homeworks/{self.own.pk}/"
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "HOMEWORK_ASSIGNMENT_ENDED")
        self.assertTrue(Homework.objects.filter(pk=self.own.pk).exists())

    def test_teacher_can_crud_homework_for_future_assignment(self):
        assignment = self.dated_assignment(
            start_date=timezone.localdate() + timedelta(days=1),
        )
        self.authenticate_teacher_with_permissions(
            "add_homework",
            "change_homework",
            "delete_homework",
        )

        create_response = self.client.post(
            "/api/v1/homework/homeworks/",
            self.payload(assignment),
            format="json",
        )
        self.assertEqual(create_response.status_code, 201)
        homework = Homework.objects.get(
            teacher_assignment=assignment,
            title="New homework",
        )
        self.assertEqual(self.client.patch(
            f"/api/v1/homework/homeworks/{homework.pk}/",
            {"title": "Future changed"},
            format="json",
        ).status_code, 200)
        self.assertEqual(self.client.delete(
            f"/api/v1/homework/homeworks/{homework.pk}/"
        ).status_code, 200)

    def test_teacher_can_crud_homework_for_active_assignment(self):
        assignment = self.dated_assignment(
            start_date=timezone.localdate() - timedelta(days=1),
        )
        self.authenticate_teacher_with_permissions(
            "add_homework",
            "change_homework",
            "delete_homework",
        )

        create_response = self.client.post(
            "/api/v1/homework/homeworks/",
            self.payload(assignment),
            format="json",
        )
        self.assertEqual(create_response.status_code, 201)
        homework = Homework.objects.get(
            teacher_assignment=assignment,
            title="New homework",
        )
        self.assertEqual(self.client.patch(
            f"/api/v1/homework/homeworks/{homework.pk}/",
            {"title": "Active changed"},
            format="json",
        ).status_code, 200)
        self.assertEqual(self.client.delete(
            f"/api/v1/homework/homeworks/{homework.pk}/"
        ).status_code, 200)

    def test_teacher_can_crud_when_assignment_ends_today(self):
        today = timezone.localdate()
        assignment = self.dated_assignment(
            start_date=today - timedelta(days=1),
            end_date=today,
        )
        self.authenticate_teacher_with_permissions(
            "add_homework",
            "change_homework",
            "delete_homework",
        )

        create_response = self.client.post(
            "/api/v1/homework/homeworks/",
            self.payload(assignment),
            format="json",
        )
        self.assertEqual(create_response.status_code, 201)
        homework = Homework.objects.get(
            teacher_assignment=assignment,
            title="New homework",
        )
        self.assertEqual(self.client.patch(
            f"/api/v1/homework/homeworks/{homework.pk}/",
            {"title": "Today changed"},
            format="json",
        ).status_code, 200)
        self.assertEqual(self.client.delete(
            f"/api/v1/homework/homeworks/{homework.pk}/"
        ).status_code, 200)

    def test_ended_assignment_does_not_change_non_teacher_behavior(self):
        self.end_assignment_yesterday(self.assignment)
        for codename in (
            "homework.add_homework",
            "homework.change_homework",
            "homework.delete_homework",
        ):
            self.grant(self.admin, codename)
        self.client.force_authenticate(
            self.admin,
            token={"client": "web"},
        )

        create_response = self.client.post(
            "/api/v1/homework/homeworks/",
            self.payload(self.assignment),
            format="json",
        )
        self.assertEqual(create_response.status_code, 201)
        homework = Homework.objects.filter(
            teacher_assignment=self.assignment,
            title="New homework",
        ).latest("created_at")
        self.assertEqual(self.client.patch(
            f"/api/v1/homework/homeworks/{homework.pk}/",
            {"title": "Admin changed"},
            format="json",
        ).status_code, 200)
        self.assertEqual(self.client.delete(
            f"/api/v1/homework/homeworks/{homework.pk}/"
        ).status_code, 200)

    def test_teacher_permissions_and_assignment_scope(self):
        url = "/api/v1/homework/homeworks/"
        self.client.force_authenticate(self.teacher, token={"client": "web"})
        self.assertEqual(self.client.get(url).status_code, 403)
        self.grant(self.teacher, "homework.view_homework")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["data"]["results"]], [str(self.own.pk)])
        self.assertEqual(self.client.get(f"{url}{self.own.pk}/").status_code, 200)
        self.assertEqual(self.client.get(f"{url}{self.other.pk}/").status_code, 404)
        self.assertEqual(self.client.post(url, self.payload(self.assignment)).status_code, 403)
        self.grant(self.teacher, "homework.add_homework")
        self.assertEqual(self.client.post(url, self.payload(self.assignment)).status_code, 201)
        self.assertEqual(self.client.post(url, self.payload(self.other_assignment)).status_code, 403)
        self.assertEqual(self.client.patch(f"{url}{self.own.pk}/", {"title": "Changed"}).status_code, 403)
        self.grant(self.teacher, "homework.change_homework")
        self.assertEqual(self.client.patch(f"{url}{self.own.pk}/", {"title": "Changed"}).status_code, 200)
        self.assertEqual(self.client.patch(f"{url}{self.other.pk}/", {"title": "Changed"}).status_code, 404)
        self.assertEqual(self.client.delete(f"{url}{self.own.pk}/").status_code, 403)
        self.grant(self.teacher, "homework.delete_homework")
        self.assertEqual(self.client.delete(f"{url}{self.other.pk}/").status_code, 404)
        self.assertEqual(self.client.delete(f"{url}{self.own.pk}/").status_code, 200)

    def test_direct_permission_removes_role_ceiling_and_superuser_bypasses(self):
        url = "/api/v1/homework/homeworks/"
        tech = self.user("homework-tech", User.Role.TECH_SUPPORT)
        self.client.force_authenticate(tech, token={"client": "web"})
        self.assertEqual(self.client.get(url).status_code, 403)
        self.grant(tech, "homework.view_homework")
        self.assertEqual(self.client.get(f"{url}{self.other.pk}/").status_code, 200)
        self.client.force_authenticate(tech, token={"client": "mobile"})
        self.assertEqual(self.client.get(url).status_code, 403)
        guardian = self.user("homework-guardian", User.Role.GUARDIAN)
        self.grant(guardian, "homework.view_homework")
        self.client.force_authenticate(guardian, token={"client": "web"})
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_authenticate(self.admin, token={"client": "web"})
        self.assertEqual(self.client.get(url).status_code, 403)
        root = User.objects.create_superuser(username="homework-root", password="StrongPass!123")
        self.client.force_authenticate(root, token={"client": "web"})
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.put(f"{url}{self.other.pk}/", {}).status_code, 405)
