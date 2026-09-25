from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from academics.models import AcademicYear, GradeLevel, Section
from students.models import Enrollment, GuardianStudent, Student

from .models import StudentPointEntry


class MobileStudentPointsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.guardian = self.make_user("points-mobile-guardian", User.Role.GUARDIAN)
        self.other_guardian = self.make_user(
            "points-mobile-other-guardian",
            User.Role.GUARDIAN,
        )
        self.staff = self.make_user("points-mobile-staff", User.Role.SCHOOL_ADMIN)
        self.non_guardian = self.make_user(
            "points-mobile-non-guardian",
            User.Role.TEACHER,
        )
        self.active_year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )
        self.old_year = AcademicYear.objects.create(
            start_date=date(2025, 9, 1),
            end_date=date(2026, 6, 30),
            status=AcademicYear.Status.CLOSED,
        )
        self.grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY,
            name="Mobile points grade",
        )
        self.active_section = Section.objects.create(
            academic_year=self.active_year,
            grade_level=self.grade,
            name="Active A",
        )
        self.old_section = Section.objects.create(
            academic_year=self.old_year,
            grade_level=self.grade,
            name="Old A",
        )
        self.child = self.make_child("Owned", self.guardian)
        self.other_child = self.make_child("Other", self.other_guardian)
        self.child_without_current_enrollment = self.make_child(
            "No Enrollment",
            self.guardian,
        )
        self.enrollment = Enrollment.objects.create(
            student=self.child,
            academic_year=self.active_year,
            section=self.active_section,
            enrollment_date=self.active_year.start_date,
        )
        self.old_enrollment = Enrollment.objects.create(
            student=self.child,
            academic_year=self.old_year,
            section=self.old_section,
            enrollment_date=self.old_year.start_date,
        )

    @staticmethod
    def make_user(username, role):
        return User.objects.create_user(
            username=username,
            password="StrongPass!493",
            role=role,
            must_change_password=False,
        )

    @staticmethod
    def make_child(first_name, guardian):
        student = Student.objects.create(
            first_name=first_name,
            last_name="Child",
            birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )
        GuardianStudent.objects.create(
            guardian=guardian,
            student=student,
            is_active=True,
        )
        return student

    def url(self, child=None):
        return f"/api/v1/mobile/children/{(child or self.child).pk}/points/"

    def authenticate(self, *, user=None, client="mobile"):
        user = user or self.guardian
        refresh = RefreshToken.for_user(user)
        refresh["client"] = client
        refresh["token_version"] = user.token_version
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}"
        )

    def point(self, points, occurred_on, *, enrollment=None, note=None):
        return StudentPointEntry.objects.create(
            enrollment=enrollment or self.enrollment,
            points=points,
            note=note or f"سبب منح {points} نقاط",
            occurred_on=occurred_on,
            created_by=self.staff,
        )

    def test_guardian_sees_owned_child_points_and_correct_summary(self):
        first = self.point(10, date(2026, 9, 1))
        second = self.point(25, date(2026, 9, 2))
        self.authenticate()
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        data = response.data["data"]
        self.assertEqual(data["summary"], {"total_points": 35, "entries_count": 2})
        self.assertEqual(
            [entry["id"] for entry in data["entries"]],
            [str(second.pk), str(first.pk)],
        )

    def test_other_family_child_returns_not_found(self):
        self.authenticate()
        self.assertEqual(self.client.get(self.url(self.other_child)).status_code, 404)

    def test_unauthenticated_request_is_rejected(self):
        self.assertEqual(self.client.get(self.url()).status_code, 401)

    def test_web_token_is_rejected(self):
        self.authenticate(client="web")
        self.assertEqual(self.client.get(self.url()).status_code, 401)

    def test_mobile_non_guardian_is_rejected(self):
        self.authenticate(user=self.non_guardian)
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_must_change_password_gate_is_preserved(self):
        self.guardian.must_change_password = True
        self.guardian.save(update_fields=["must_change_password"])
        self.authenticate()
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_only_active_year_enrollment_points_are_returned(self):
        self.point(30, date(2025, 9, 1), enrollment=self.old_enrollment)
        current = self.point(12, date(2026, 9, 1))
        self.authenticate()
        data = self.client.get(self.url()).data["data"]
        self.assertEqual(data["summary"], {"total_points": 12, "entries_count": 1})
        self.assertEqual([entry["id"] for entry in data["entries"]], [str(current.pk)])

    def test_missing_current_enrollment_returns_empty_success(self):
        self.authenticate()
        response = self.client.get(self.url(self.child_without_current_enrollment))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["data"],
            {
                "summary": {"total_points": 0, "entries_count": 0},
                "entries": [],
            },
        )

    def test_missing_active_year_returns_empty_success(self):
        self.point(10, date(2026, 9, 1))
        self.active_year.status = AcademicYear.Status.CLOSED
        self.active_year.save(update_fields=["status"])
        self.authenticate()
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["data"],
            {
                "summary": {"total_points": 0, "entries_count": 0},
                "entries": [],
            },
        )

    def test_section_transfer_keeps_points_for_same_enrollment(self):
        entry = self.point(18, date(2026, 9, 1))
        new_section = Section.objects.create(
            academic_year=self.active_year,
            grade_level=self.grade,
            name="Active B",
        )
        self.enrollment.section = new_section
        self.enrollment.save(update_fields=["section"])
        self.authenticate()
        data = self.client.get(self.url()).data["data"]
        self.assertEqual([item["id"] for item in data["entries"]], [str(entry.pk)])

    def test_pagination_does_not_change_full_summary(self):
        for day in range(1, 26):
            self.point(2, date(2026, 9, day))
        self.authenticate()
        response = self.client.get(self.url(), {"page_size": 10})
        self.assertEqual(len(response.data["data"]["entries"]), 10)
        self.assertEqual(
            response.data["data"]["summary"],
            {"total_points": 50, "entries_count": 25},
        )
        self.assertEqual(response.data["meta"]["pagination"]["count"], 25)

    def test_date_from_filters_entries_and_summary(self):
        self.point(5, date(2026, 9, 1))
        included = self.point(10, date(2026, 9, 15))
        self.authenticate()
        data = self.client.get(
            self.url(),
            {"date_from": "2026-09-10"},
        ).data["data"]
        self.assertEqual(data["summary"], {"total_points": 10, "entries_count": 1})
        self.assertEqual([item["id"] for item in data["entries"]], [str(included.pk)])

    def test_date_to_filters_entries_and_summary(self):
        included = self.point(5, date(2026, 9, 1))
        self.point(10, date(2026, 9, 15))
        self.authenticate()
        data = self.client.get(
            self.url(),
            {"date_to": "2026-09-10"},
        ).data["data"]
        self.assertEqual(data["summary"], {"total_points": 5, "entries_count": 1})
        self.assertEqual([item["id"] for item in data["entries"]], [str(included.pk)])

    def test_date_range_filters_entries_and_summary(self):
        self.point(5, date(2026, 9, 1))
        included = self.point(10, date(2026, 9, 15))
        self.point(20, date(2026, 10, 1))
        self.authenticate()
        data = self.client.get(self.url(), {
            "date_from": "2026-09-10",
            "date_to": "2026-09-30",
        }).data["data"]
        self.assertEqual(data["summary"], {"total_points": 10, "entries_count": 1})
        self.assertEqual([item["id"] for item in data["entries"]], [str(included.pk)])

    def test_invalid_date_range_is_rejected(self):
        self.authenticate()
        response = self.client.get(self.url(), {
            "date_from": "2026-10-01",
            "date_to": "2026-09-01",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("date_to", response.data["errors"])

    def test_response_exposes_only_guardian_fields(self):
        self.point(10, date(2026, 9, 1), note="مشاركة مميزة")
        self.authenticate()
        entry = self.client.get(self.url()).data["data"]["entries"][0]
        self.assertEqual(set(entry), {"id", "points", "note", "occurred_on"})
        for private_field in (
            "enrollment",
            "enrollment_id",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ):
            self.assertNotIn(private_field, entry)

    def test_endpoint_is_read_only(self):
        self.authenticate()
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(self.url(), {}, format="json")
                self.assertEqual(response.status_code, 405)
