from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, GradeSubject, Section, Subject, Term
from accounts.models import User
from audit_logs.models import AuditLog
from teaching.models import TeacherAssignment

from .models import Assessment, AssessmentSection


class AssessmentSchedulePublishingApiTests(TestCase):
    publish_url = "/api/v1/grades/assessments/publish-schedule/"
    unpublish_url = "/api/v1/grades/assessments/unpublish-schedule/"

    def setUp(self):
        self.year = AcademicYear.objects.create(
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
        )
        self.term = Term.objects.create(
            academic_year=self.year, number=Term.Number.FIRST,
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        )
        self.grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="الأول")
        self.section = Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name="أ"
        )
        self.other_section = Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name="ب"
        )
        subject = Subject.objects.create(name="الرياضيات")
        self.grade_subject = GradeSubject.objects.create(
            academic_year=self.year, grade_level=self.grade, subject=subject
        )
        self.admin = self.make_user("schedule-admin", User.Role.SCHOOL_ADMIN)
        self.teacher = self.make_user("schedule-teacher", User.Role.TEACHER)
        self.assessment = Assessment.objects.create(
            grade_subject=self.grade_subject, term=self.term,
            title="امتحان مستقبلي", max_score=Decimal("20"),
            assessment_date=date(2026, 11, 1), created_by=self.admin,
        )
        self.link = AssessmentSection.objects.create(
            assessment=self.assessment, section=self.section
        )
        self.permission = Permission.objects.get(
            content_type__app_label="grades",
            codename="publish_assessment_schedule",
        )
        self.admin.user_permissions.add(self.permission)
        self.client = self.client_for(self.admin)

    def make_user(self, username, role):
        return User.objects.create_user(
            username=username, password="x", role=role, must_change_password=False
        )

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user, token={"client": "web"})
        return client

    def payload(self, assessment=None, section=None):
        return {
            "assessment": str((assessment or self.assessment).id),
            "section": str((section or self.section).id),
        }

    def publish(self, client=None, **payload_overrides):
        payload = self.payload()
        payload.update(payload_overrides)
        return (client or self.client).post(self.publish_url, payload, format="json")

    def test_future_assessment_without_scores_can_be_published(self):
        response = self.publish()
        self.assertEqual(response.status_code, 200)

    def test_publish_sets_all_schedule_fields(self):
        self.publish()
        self.link.refresh_from_db()
        self.assertEqual(self.link.schedule_status, AssessmentSection.ScheduleStatus.PUBLISHED)
        self.assertEqual(self.link.schedule_published_by, self.admin)
        self.assertIsNotNone(self.link.schedule_published_at)

    def test_publish_does_not_change_result_status(self):
        self.publish()
        self.link.refresh_from_db()
        self.assertEqual(self.link.status, AssessmentSection.Status.DRAFT)

    def test_repeated_publish_preserves_original_actor_and_time(self):
        self.publish()
        self.link.refresh_from_db()
        actor_id = self.link.schedule_published_by_id
        published_at = self.link.schedule_published_at
        self.assertEqual(self.publish().status_code, 200)
        self.link.refresh_from_db()
        self.assertEqual(self.link.schedule_published_by_id, actor_id)
        self.assertEqual(self.link.schedule_published_at, published_at)
        self.assertEqual(
            AuditLog.objects.filter(
                module=AuditLog.Module.GRADES,
                action=AuditLog.Action.PUBLISH,
                target_id=str(self.link.id),
            ).count(),
            1,
        )

    def test_unpublish_clears_schedule_publish_data(self):
        self.publish()
        response = self.client.post(self.unpublish_url, self.payload(), format="json")
        self.assertEqual(response.status_code, 200)
        self.link.refresh_from_db()
        self.assertEqual(self.link.schedule_status, AssessmentSection.ScheduleStatus.DRAFT)
        self.assertIsNone(self.link.schedule_published_by)
        self.assertIsNone(self.link.schedule_published_at)

    def test_repeated_unpublish_is_idempotent(self):
        self.publish()
        first = self.client.post(self.unpublish_url, self.payload(), format="json")
        second = self.client.post(self.unpublish_url, self.payload(), format="json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            AuditLog.objects.filter(
                module=AuditLog.Module.GRADES,
                action=AuditLog.Action.CANCEL,
                target_id=str(self.link.id),
            ).count(),
            1,
        )

    def test_unpublish_is_rejected_after_results_are_published(self):
        self.publish()
        self.link.refresh_from_db()
        original = (
            self.link.schedule_status,
            self.link.schedule_published_by_id,
            self.link.schedule_published_at,
        )
        self.link.status = AssessmentSection.Status.PUBLISHED
        self.link.published_by = self.admin
        self.link.published_at = timezone.now()
        self.link.save(update_fields=["status", "published_by", "published_at", "updated_at"])
        response = self.client.post(self.unpublish_url, self.payload(), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "ASSESSMENT_SCHEDULE_UNPUBLISH_NOT_ALLOWED")
        self.link.refresh_from_db()
        self.assertEqual(
            (self.link.schedule_status, self.link.schedule_published_by_id, self.link.schedule_published_at),
            original,
        )

    def test_user_without_permission_gets_403(self):
        self.admin.user_permissions.remove(self.permission)
        self.assertEqual(self.publish().status_code, 403)

    def test_admin_with_permission_can_publish_in_scope(self):
        self.assertEqual(self.publish().status_code, 200)

    def test_assigned_teacher_with_permission_can_publish(self):
        self.teacher.user_permissions.add(self.permission)
        TeacherAssignment.objects.create(
            teacher=self.teacher, grade_subject=self.grade_subject,
            section=self.section, start_date=date(2026, 1, 1),
        )
        self.assertEqual(self.publish(client=self.client_for(self.teacher)).status_code, 200)

    def test_teacher_without_matching_assignment_is_denied(self):
        self.teacher.user_permissions.add(self.permission)
        response = self.publish(client=self.client_for(self.teacher))
        self.assertIn(response.status_code, (403, 404))

    def test_unlinked_assessment_and_section_are_rejected(self):
        response = self.publish(section=str(self.other_section.id))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "ASSESSMENT_SECTION_MISMATCH")

    def test_out_of_scope_teacher_cannot_discover_or_change_assessment(self):
        self.teacher.user_permissions.add(self.permission)
        TeacherAssignment.objects.create(
            teacher=self.teacher, grade_subject=self.grade_subject,
            section=self.other_section, start_date=date(2026, 1, 1),
        )
        response = self.publish(client=self.client_for(self.teacher))
        self.assertEqual(response.status_code, 404)
        self.link.refresh_from_db()
        self.assertEqual(self.link.schedule_status, AssessmentSection.ScheduleStatus.DRAFT)

    def test_response_separates_schedule_and_result_statuses(self):
        response = self.publish()
        data = response.data["data"]
        self.assertEqual(data["schedule_status"], "published")
        self.assertEqual(data["result_status"], "draft")
        self.assertEqual(data["assessment"], str(self.assessment.id))
        self.assertEqual(data["section"], str(self.section.id))

    def test_regular_update_cannot_change_schedule_publish_fields(self):
        response = self.client.patch(
            f"/api/v1/grades/assessments/{self.assessment.id}/",
            {
                "title": "عنوان معدل",
                "schedule_status": "published",
                "schedule_published_by": str(self.admin.id),
                "schedule_published_at": timezone.now().isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.link.refresh_from_db()
        self.assertEqual(self.link.schedule_status, AssessmentSection.ScheduleStatus.DRAFT)
        self.assertIsNone(self.link.schedule_published_by)
        self.assertIsNone(self.link.schedule_published_at)
