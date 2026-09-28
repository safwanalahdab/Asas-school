from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from academics.models import (
    AcademicYear,
    GradeLevel,
    GradeSubject,
    Section,
    Subject,
)
from students.models import Enrollment, Student
from teaching.models import TeacherAssignment

from .models import BehaviorNote, StudentPointEntry


User = get_user_model()


class BehaviorTeacherScopeTests(TestCase):
    note_url = "/api/v1/behavior/notes/"
    point_url = "/api/v1/behavior/points/"

    def setUp(self):
        self.today = timezone.localdate()
        self.client = APIClient()
        self.teacher = self.make_user("behavior-scope-teacher", User.Role.TEACHER)
        self.other_teacher = self.make_user(
            "behavior-scope-other-teacher",
            User.Role.TEACHER,
        )
        self.admin = self.make_user("behavior-scope-admin", User.Role.SCHOOL_ADMIN)
        self.grant(
            self.teacher,
            "view_behaviornote",
            "add_behaviornote",
            "change_behaviornote",
            "delete_behaviornote",
            "view_studentpointentry",
            "add_studentpointentry",
            "change_studentpointentry",
            "delete_studentpointentry",
        )
        self.year = AcademicYear.objects.create(
            start_date=self.today - timedelta(days=100),
            end_date=self.today + timedelta(days=400),
        )
        self.grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY,
            name="Behavior teacher scope grade",
        )
        subject = Subject.objects.create(name="Behavior teacher scope subject")
        self.grade_subject = GradeSubject.objects.create(
            academic_year=self.year,
            grade_level=self.grade,
            subject=subject,
        )
        self.scopes = {
            "future": self.make_scope(
                "Future",
                teacher=self.teacher,
                start_date=self.today + timedelta(days=30),
            ),
            "active": self.make_scope(
                "Active",
                teacher=self.teacher,
                start_date=self.today - timedelta(days=30),
            ),
            "today": self.make_scope(
                "Today",
                teacher=self.teacher,
                start_date=self.today - timedelta(days=30),
                end_date=self.today,
            ),
            "ended": self.make_scope(
                "Ended",
                teacher=self.teacher,
                start_date=self.today - timedelta(days=30),
                end_date=self.today - timedelta(days=1),
            ),
            "other": self.make_scope(
                "Other",
                teacher=self.other_teacher,
                start_date=self.today - timedelta(days=30),
            ),
            "unassigned": self.make_scope("Unassigned"),
        }
        self.client.force_authenticate(
            self.teacher,
            token={"client": "web"},
        )

    @staticmethod
    def make_user(username, role):
        return User.objects.create_user(
            username=username,
            password="StrongPass!123",
            role=role,
            must_change_password=False,
        )

    @staticmethod
    def grant(user, *codenames):
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="behavior",
            codename__in=codenames,
        ))

    def make_scope(
        self,
        label,
        *,
        teacher=None,
        start_date=None,
        end_date=None,
    ):
        section = Section.objects.create(
            academic_year=self.year,
            grade_level=self.grade,
            name=label,
        )
        student = Student.objects.create(
            first_name=label,
            last_name="Student",
            birth_date=self.today - timedelta(days=3650),
            gender=Student.Gender.MALE,
        )
        enrollment = Enrollment.objects.create(
            student=student,
            academic_year=self.year,
            section=section,
            enrollment_date=self.year.start_date,
        )
        if teacher is not None:
            TeacherAssignment.objects.create(
                teacher=teacher,
                grade_subject=self.grade_subject,
                section=section,
                start_date=start_date,
                end_date=end_date,
            )
        note = BehaviorNote.objects.create(
            enrollment=enrollment,
            note_type=BehaviorNote.Type.POSITIVE,
            title=f"{label} note",
            description="Description",
            occurred_on=self.today,
            created_by=self.admin,
        )
        point = StudentPointEntry.objects.create(
            enrollment=enrollment,
            points=10,
            note=f"{label} point",
            occurred_on=self.today,
            created_by=self.admin,
        )
        return {
            "section": section,
            "enrollment": enrollment,
            "note": note,
            "point": point,
        }

    @staticmethod
    def rows(response):
        data = response.data["data"]
        return data.get("results", data) if isinstance(data, dict) else data

    def note_payload(self, enrollment):
        return {
            "enrollment": str(enrollment.pk),
            "note_type": BehaviorNote.Type.POSITIVE,
            "title": "Scoped note",
            "description": "Description",
            "occurred_on": self.today.isoformat(),
        }

    def point_payload(self, enrollment):
        return {
            "enrollment": str(enrollment.pk),
            "points": 15,
            "note": "Scoped point",
            "occurred_on": self.today.isoformat(),
        }

    def test_teacher_behavior_note_list_and_retrieve_are_scoped(self):
        response = self.client.get(self.note_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {row["id"] for row in self.rows(response)},
            {
                str(self.scopes[name]["note"].pk)
                for name in ("future", "active", "today")
            },
        )
        self.assertEqual(self.client.get(
            f"{self.note_url}{self.scopes['future']['note'].pk}/"
        ).status_code, 200)
        for name in ("ended", "other", "unassigned"):
            with self.subTest(scope=name):
                self.assertEqual(self.client.get(
                    f"{self.note_url}{self.scopes[name]['note'].pk}/"
                ).status_code, 404)

    def test_teacher_behavior_note_create_respects_assignment_dates_and_owner(self):
        for name in ("future", "active", "today"):
            with self.subTest(scope=name):
                self.assertEqual(self.client.post(
                    self.note_url,
                    self.note_payload(self.scopes[name]["enrollment"]),
                    format="json",
                ).status_code, 201)
        for name in ("ended", "other", "unassigned"):
            with self.subTest(scope=name):
                response = self.client.post(
                    self.note_url,
                    self.note_payload(self.scopes[name]["enrollment"]),
                    format="json",
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(
                    response.data["code"],
                    "TEACHER_STUDENT_SCOPE_DENIED",
                )

    def test_teacher_behavior_note_update_delete_and_reassignment_are_scoped(self):
        active_note = self.scopes["active"]["note"]
        ended_note = self.scopes["ended"]["note"]
        self.assertEqual(self.client.patch(
            f"{self.note_url}{active_note.pk}/",
            {"title": "Changed"},
            format="json",
        ).status_code, 200)
        self.assertEqual(self.client.patch(
            f"{self.note_url}{ended_note.pk}/",
            {"title": "Blocked"},
            format="json",
        ).status_code, 404)
        self.assertEqual(self.client.delete(
            f"{self.note_url}{ended_note.pk}/"
        ).status_code, 404)

        response = self.client.patch(
            f"{self.note_url}{active_note.pk}/",
            {"enrollment": str(self.scopes["ended"]["enrollment"].pk)},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data["code"],
            "TEACHER_STUDENT_SCOPE_DENIED",
        )
        active_note.refresh_from_db()
        self.assertEqual(
            active_note.enrollment_id,
            self.scopes["active"]["enrollment"].pk,
        )
        self.assertEqual(self.client.delete(
            f"{self.note_url}{active_note.pk}/"
        ).status_code, 200)

    def test_teacher_point_list_and_retrieve_are_scoped(self):
        response = self.client.get(self.point_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {row["id"] for row in self.rows(response)},
            {
                str(self.scopes[name]["point"].pk)
                for name in ("future", "active", "today")
            },
        )
        self.assertEqual(self.client.get(
            f"{self.point_url}{self.scopes['today']['point'].pk}/"
        ).status_code, 200)
        for name in ("ended", "other", "unassigned"):
            with self.subTest(scope=name):
                self.assertEqual(self.client.get(
                    f"{self.point_url}{self.scopes[name]['point'].pk}/"
                ).status_code, 404)

    def test_teacher_point_create_respects_assignment_dates_and_owner(self):
        for name in ("future", "active", "today"):
            with self.subTest(scope=name):
                self.assertEqual(self.client.post(
                    self.point_url,
                    self.point_payload(self.scopes[name]["enrollment"]),
                    format="json",
                ).status_code, 201)
        for name in ("ended", "other", "unassigned"):
            with self.subTest(scope=name):
                response = self.client.post(
                    self.point_url,
                    self.point_payload(self.scopes[name]["enrollment"]),
                    format="json",
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(
                    response.data["code"],
                    "TEACHER_STUDENT_SCOPE_DENIED",
                )

    def test_teacher_point_update_delete_and_reassignment_are_scoped(self):
        active_point = self.scopes["active"]["point"]
        ended_point = self.scopes["ended"]["point"]
        self.assertEqual(self.client.patch(
            f"{self.point_url}{active_point.pk}/",
            {"points": 20},
            format="json",
        ).status_code, 200)
        self.assertEqual(self.client.patch(
            f"{self.point_url}{ended_point.pk}/",
            {"points": 20},
            format="json",
        ).status_code, 404)
        self.assertEqual(self.client.delete(
            f"{self.point_url}{ended_point.pk}/"
        ).status_code, 404)

        response = self.client.patch(
            f"{self.point_url}{active_point.pk}/",
            {"enrollment": str(self.scopes["other"]["enrollment"].pk)},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data["code"],
            "TEACHER_STUDENT_SCOPE_DENIED",
        )
        active_point.refresh_from_db()
        self.assertEqual(
            active_point.enrollment_id,
            self.scopes["active"]["enrollment"].pk,
        )
        self.assertEqual(self.client.delete(
            f"{self.point_url}{active_point.pk}/"
        ).status_code, 200)

    def test_teacher_still_requires_direct_business_permissions(self):
        teacher = self.make_user(
            "behavior-scope-no-permissions",
            User.Role.TEACHER,
        )
        TeacherAssignment.objects.create(
            teacher=teacher,
            grade_subject=self.grade_subject,
            section=self.scopes["active"]["section"],
            start_date=self.today - timedelta(days=1),
        )
        self.client.force_authenticate(teacher, token={"client": "web"})

        self.assertEqual(self.client.get(self.note_url).status_code, 403)
        self.assertEqual(self.client.get(self.point_url).status_code, 403)

    def test_non_teacher_behavior_is_unchanged(self):
        self.grant(
            self.admin,
            "view_behaviornote",
            "add_behaviornote",
            "view_studentpointentry",
            "add_studentpointentry",
        )
        self.client.force_authenticate(self.admin, token={"client": "web"})

        self.assertEqual(
            len(self.rows(self.client.get(self.note_url))),
            len(self.scopes),
        )
        self.assertEqual(
            len(self.rows(self.client.get(self.point_url))),
            len(self.scopes),
        )
        self.assertEqual(self.client.post(
            self.note_url,
            self.note_payload(self.scopes["ended"]["enrollment"]),
            format="json",
        ).status_code, 201)
        self.assertEqual(self.client.post(
            self.point_url,
            self.point_payload(self.scopes["ended"]["enrollment"]),
            format="json",
        ).status_code, 201)
