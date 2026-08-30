from datetime import date, datetime
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from academics.models import AcademicYear, GradeLevel, Section
from students.models import Enrollment, GuardianStudent, Student

from .models import BehaviorNote


User = get_user_model()


class MobileBehaviorTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.guardian = self.make_user("behavior-guardian")
        self.other_guardian = self.make_user("behavior-other")
        self.staff = User.objects.create_user(
            username="behavior-staff", password="StrongPass!493",
            role=User.Role.SCHOOL_ADMIN, must_change_password=False,
        )
        self.current_year = self.make_year(2026, AcademicYear.Status.ACTIVE)
        self.old_year = self.make_year(2025, AcademicYear.Status.CLOSED)
        self.grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY, name="Grade Mobile Behavior",
        )
        self.section = Section.objects.create(
            academic_year=self.current_year, grade_level=self.grade, name="A",
        )
        self.old_section = Section.objects.create(
            academic_year=self.old_year, grade_level=self.grade, name="Old",
        )
        self.child = self.make_child("Owned", self.guardian)
        self.other_child = self.make_child("Other", self.other_guardian)
        self.enrollment = Enrollment.objects.create(
            student=self.child, academic_year=self.current_year,
            section=self.section, enrollment_date=date(2026, 1, 1),
        )
        self.old_enrollment = Enrollment.objects.create(
            student=self.child, academic_year=self.old_year,
            section=self.old_section, enrollment_date=date(2025, 1, 1),
        )

    def make_user(self, username):
        return User.objects.create_user(
            username=username, password="StrongPass!493",
            role=User.Role.GUARDIAN, must_change_password=False,
        )

    def make_year(self, year, status):
        return AcademicYear.objects.create(
            start_date=date(year, 1, 1), end_date=date(year, 12, 31), status=status,
        )

    def make_child(self, name, guardian):
        child = Student.objects.create(
            first_name=name, last_name="Child", birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )
        GuardianStudent.objects.create(guardian=guardian, student=child)
        return child

    def url(self, child=None):
        return f"/api/v1/mobile/children/{(child or self.child).id}/behavior/"

    def authenticate(self, client="mobile"):
        token = RefreshToken.for_user(self.guardian)
        token["client"] = client
        token["token_version"] = self.guardian.token_version
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    def note(self, kind, title, occurred_on, enrollment=None):
        return BehaviorNote.objects.create(
            enrollment=enrollment or self.enrollment, note_type=kind,
            title=title, description=f"Description {title}",
            occurred_on=occurred_on, created_by=self.staff,
        )

    def test_notes_summary_order_fields_and_current_enrollment(self):
        first = self.note(BehaviorNote.Type.POSITIVE, "First", date(2026, 8, 29))
        second = self.note(BehaviorNote.Type.NEGATIVE, "Second", date(2026, 8, 30))
        old = self.note(BehaviorNote.Type.NEGATIVE, "Old", date(2025, 5, 1), self.old_enrollment)
        BehaviorNote.objects.filter(pk=first.pk).update(
            created_at=timezone.make_aware(datetime(2026, 8, 29, 8))
        )
        self.authenticate()
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        data = response.data["data"]
        self.assertEqual(data["summary"], {
            "total_notes_count": 2,
            "positive_notes_count": 1,
            "negative_notes_count": 1,
        })
        self.assertEqual([item["id"] for item in data["notes"]], [str(second.id), str(first.id)])
        self.assertNotIn(str(old.id), [item["id"] for item in data["notes"]])
        self.assertEqual(set(data["notes"][0]), {
            "id", "note_type", "note_type_display", "title", "description", "occurred_on",
        })
        self.assertNotIn("created_by", data["notes"][0])
        self.assertNotIn("enrollment", data["notes"][0])

    def test_section_transfer_keeps_same_enrollment_notes(self):
        note = self.note(BehaviorNote.Type.POSITIVE, "Transfer", date(2026, 8, 30))
        new_section = Section.objects.create(
            academic_year=self.current_year, grade_level=self.grade, name="B",
        )
        self.enrollment.section = new_section
        self.enrollment.save(update_fields=["section"])
        self.authenticate()
        ids = [item["id"] for item in self.client.get(self.url()).data["data"]["notes"]]
        self.assertIn(str(note.id), ids)

    def test_no_enrollment_returns_empty_success(self):
        child = self.make_child("NoEnrollment", self.guardian)
        self.authenticate()
        data = self.client.get(self.url(child)).data["data"]
        self.assertIsNone(data["academic_year"])
        self.assertEqual(data["notes"], [])
        self.assertEqual(data["summary"]["total_notes_count"], 0)

    def test_security_boundaries(self):
        self.authenticate()
        self.assertEqual(self.client.get(self.url(self.other_child)).status_code, 404)
        self.client.credentials()
        self.assertEqual(self.client.get(self.url()).status_code, 401)
        self.authenticate(client="web")
        self.assertEqual(self.client.get(self.url()).status_code, 401)
        self.guardian.must_change_password = True
        self.guardian.save(update_fields=["must_change_password"])
        self.authenticate()
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_only_get_is_allowed(self):
        self.authenticate()
        for method in ("post", "put", "patch", "delete"):
            self.assertEqual(getattr(self.client, method)(self.url(), {}).status_code, 405)
