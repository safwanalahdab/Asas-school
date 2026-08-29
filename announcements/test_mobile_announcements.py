from datetime import date, timedelta
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from academics.models import AcademicYear, GradeLevel, Section
from students.models import Enrollment, GuardianStudent, Student

from .models import Announcement

User = get_user_model()


class MobileAnnouncementsApiTests(TestCase):
    def setUp(self):
        self.media_directory = TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        media_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        media_override.enable()
        self.addCleanup(media_override.disable)
        self.client = APIClient()
        self.today = timezone.localdate()
        self.guardian = User.objects.create_user(
            username="announcement-guardian", password="StrongPass!493",
            role=User.Role.GUARDIAN, must_change_password=False,
        )
        self.other_guardian = User.objects.create_user(
            username="other-announcement-guardian", password="StrongPass!493",
            role=User.Role.GUARDIAN, must_change_password=False,
        )
        self.creator = User.objects.create_user(
            username="announcement-admin", password="StrongPass!493",
            role=User.Role.SCHOOL_ADMIN, must_change_password=False,
        )
        self.year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1), end_date=date(2027, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )
        self.grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="السادس")
        self.other_grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="السابع")
        self.section = Section.objects.create(academic_year=self.year, grade_level=self.grade, name="أ")
        self.other_section = Section.objects.create(academic_year=self.year, grade_level=self.other_grade, name="ب")
        self.child = self.create_child(self.guardian, "طفل")
        self.no_enrollment = self.create_child(self.guardian, "بلا تسجيل", enroll=False)
        self.other_child = self.create_child(self.other_guardian, "عائلة أخرى")
        self.all_announcement = self.create_announcement(Announcement.Scope.ALL, "الكل")
        self.grade_announcement = self.create_announcement(Announcement.Scope.GRADES, "الصف")
        self.grade_announcement.grade_levels.add(self.grade)
        self.section_announcement = self.create_announcement(Announcement.Scope.SECTIONS, "الشعبة")
        self.section_announcement.sections.add(self.section)
        other_grade = self.create_announcement(Announcement.Scope.GRADES, "صف آخر")
        other_grade.grade_levels.add(self.other_grade)
        other_section = self.create_announcement(Announcement.Scope.SECTIONS, "شعبة أخرى")
        other_section.sections.add(self.other_section)

    def create_child(self, guardian, first_name, enroll=True):
        child = Student.objects.create(
            first_name=first_name, last_name="محمد", birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )
        GuardianStudent.objects.create(guardian=guardian, student=child)
        if enroll:
            Enrollment.objects.create(
                student=child, academic_year=self.year, section=self.section,
                enrollment_date=date(2026, 9, 1),
            )
        return child

    def create_announcement(
        self,
        scope,
        title,
        publish_date=None,
        expiry_date=None,
        attachment=None,
    ):
        return Announcement.objects.create(
            scope=scope, title=title, content="المحتوى",
            publish_date=publish_date or self.today, expiry_date=expiry_date,
            attachment=attachment, created_by=self.creator,
        )

    def url(self, child=None):
        return f"/api/v1/mobile/children/{(child or self.child).id}/announcements/"

    def authenticate(self, client="mobile"):
        refresh = RefreshToken.for_user(self.guardian)
        refresh["client"] = client
        refresh["token_version"] = self.guardian.token_version
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def test_scope_matching_returns_all_grade_and_section_only(self):
        self.authenticate()
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual({x["title"] for x in response.data["data"]}, {"الكل", "الصف", "الشعبة"})

    def test_temporal_visibility_boundaries(self):
        self.create_announcement(Announcement.Scope.ALL, "مستقبلي", self.today + timedelta(days=1))
        self.create_announcement(Announcement.Scope.ALL, "منتهي", self.today - timedelta(days=2), self.today - timedelta(days=1))
        self.create_announcement(Announcement.Scope.ALL, "ينتهي اليوم", self.today - timedelta(days=1), self.today)
        self.create_announcement(Announcement.Scope.ALL, "بدون انتهاء", self.today - timedelta(days=10), None)
        self.authenticate()
        titles = {x["title"] for x in self.client.get(self.url()).data["data"]}
        self.assertNotIn("مستقبلي", titles)
        self.assertNotIn("منتهي", titles)
        self.assertIn("ينتهي اليوم", titles)
        self.assertIn("بدون انتهاء", titles)

    def test_many_to_many_joins_do_not_duplicate(self):
        duplicate_candidate = self.create_announcement(Announcement.Scope.GRADES, "غير مكرر")
        duplicate_candidate.grade_levels.add(self.grade, self.other_grade)
        self.authenticate()
        titles = [x["title"] for x in self.client.get(self.url()).data["data"]]
        self.assertEqual(titles.count("غير مكرر"), 1)

    def test_unowned_child_is_hidden_and_missing_enrollment_is_empty(self):
        self.authenticate()
        self.assertEqual(self.client.get(self.url(self.other_child)).status_code, 404)
        response = self.client.get(self.url(self.no_enrollment))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"], [])

    def test_child_with_historical_enrollment_only_gets_empty_announcements(self):
        historical_year = AcademicYear.objects.create(
            start_date=date(2025, 9, 1),
            end_date=date(2026, 6, 30),
            status=AcademicYear.Status.CLOSED,
        )
        historical_section = Section.objects.create(
            academic_year=historical_year,
            grade_level=self.grade,
            name="تاريخية",
        )
        historical_child = Student.objects.create(
            first_name="تاريخي",
            last_name="محمد",
            birth_date=date(2015, 3, 1),
            gender=Student.Gender.MALE,
        )
        GuardianStudent.objects.create(
            guardian=self.guardian,
            student=historical_child,
            is_active=True,
        )
        Enrollment.objects.create(
            student=historical_child,
            academic_year=historical_year,
            section=historical_section,
            enrollment_date=date(2025, 9, 1),
        )
        self.authenticate()

        response = self.client.get(self.url(historical_child))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["code"],
            "MOBILE_CHILD_ANNOUNCEMENTS_RETRIEVED",
        )
        self.assertEqual(response.data["data"], [])

    def test_auth_password_gate_and_methods(self):
        self.assertEqual(self.client.get(self.url()).status_code, 401)
        self.authenticate(client="web")
        self.assertEqual(self.client.get(self.url()).status_code, 401)
        self.guardian.must_change_password = True
        self.guardian.save(update_fields=["must_change_password"])
        self.authenticate()
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.guardian.must_change_password = False
        self.guardian.save(update_fields=["must_change_password"])
        self.authenticate()
        for method in (
            self.client.post,
            self.client.put,
            self.client.patch,
            self.client.delete,
        ):
            response = method(self.url(), {}, format="json")
            self.assertEqual(response.status_code, 405)
            self.assertFalse(response.data["success"])
            self.assertEqual(response.data["code"], "METHOD_NOT_ALLOWED")

    def test_attachment_is_returned_as_absolute_url(self):
        announcement = self.create_announcement(
            Announcement.Scope.ALL,
            "إعلان مرفق",
            attachment=SimpleUploadedFile("notice.txt", b"notice"),
        )
        self.authenticate()

        response = self.client.get(self.url())
        item = next(
            result
            for result in response.data["data"]
            if result["id"] == str(announcement.id)
        )

        self.assertIsNotNone(item["attachment"])
        self.assertTrue(item["attachment"].startswith("http://testserver/"))

    def test_announcements_are_ordered_by_publish_date_then_created_at(self):
        older_date = self.today - timedelta(days=2)
        older = self.create_announcement(
            Announcement.Scope.ALL,
            "أقدم تاريخًا",
            publish_date=older_date,
        )
        first_same_day = self.create_announcement(
            Announcement.Scope.ALL,
            "الأول في اليوم",
            publish_date=self.today,
        )
        second_same_day = self.create_announcement(
            Announcement.Scope.ALL,
            "الثاني في اليوم",
            publish_date=self.today,
        )
        created_at = timezone.now()
        Announcement.objects.filter(pk=first_same_day.pk).update(
            created_at=created_at,
        )
        Announcement.objects.filter(pk=second_same_day.pk).update(
            created_at=created_at + timedelta(seconds=1),
        )
        self.authenticate()

        returned_ids = [
            item["id"]
            for item in self.client.get(self.url()).data["data"]
        ]

        self.assertLess(
            returned_ids.index(str(second_same_day.id)),
            returned_ids.index(str(first_same_day.id)),
        )
        self.assertLess(
            returned_ids.index(str(first_same_day.id)),
            returned_ids.index(str(older.id)),
        )

    def test_response_is_minimal_and_attachment_null(self):
        self.authenticate()
        item = next(x for x in self.client.get(self.url()).data["data"] if x["title"] == "الكل")
        self.assertEqual(set(item), {
            "id", "title", "content", "scope", "scope_display", "publish_date",
            "expiry_date", "is_active", "attachment", "created_at",
        })
        self.assertTrue(item["is_active"])
        self.assertIsNone(item["attachment"])
        self.assertTrue({"created_by", "grade_levels", "sections"}.isdisjoint(item))
