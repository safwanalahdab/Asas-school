from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, GradeSubject, Section, Subject, Term
from finance.models import GradeTuitionPlan, StudentFinancialAccount
from finance.services import record_payment
from grades.models import ScoreAuditLog
from grades.services import create_assessment, publish_section_assessments, save_assessment_scores_bulk
from students.models import Enrollment, Student, StudentAuditLog
from students.services import transfer_student_between_sections

from .models import AuditLog
from .services import record_audit_event, sanitize_metadata

User = get_user_model()


class AuditServiceTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_user(
            username="auditor", first_name="أحمد", last_name="خالد",
            password="Strong!934", role=User.Role.SCHOOL_ADMIN,
            must_change_password=False,
        )

    def test_record_snapshots_and_json_safe_metadata(self):
        target = User.objects.create_user(
            username="target", password="Strong!934", role=User.Role.TEACHER,
        )
        event = record_audit_event(
            actor=self.actor, module=AuditLog.Module.ACCOUNTS,
            action=AuditLog.Action.CREATE,
            message="أنشأ أحمد حساب المستخدم.", target=target,
            target_display="المعلم محمد",
            metadata={"amount": Decimal("10.50"), "day": date(2026, 1, 1), "id": uuid4()},
        )
        self.assertEqual(event.actor_display, "أحمد خالد")
        self.assertEqual(event.target_display, "المعلم محمد")
        self.assertIsInstance(event.metadata["amount"], str)
        self.actor.first_name = "اسم جديد"
        self.actor.save(update_fields=["first_name"])
        event.refresh_from_db()
        self.assertEqual(event.actor_display, "أحمد خالد")

    def test_recursive_sanitization_removes_all_sensitive_keys(self):
        raw = {
            "password": "x", "temporary_password": "x", "access_token": "x",
            "refresh_token": "x", "jwt": "x", "csrf": "x",
            "cookies": "x", "Authorization": "x", "credential": "x",
            "safe": {"student": "محمد", "secret_key": "x", "items": [{"token": "x", "ok": 1}]},
        }
        self.assertEqual(
            sanitize_metadata(raw),
            {"safe": {"student": "محمد", "items": [{"ok": 1}]}},
        )

    def test_actor_set_null_preserves_snapshots(self):
        event = record_audit_event(
            actor=self.actor, module=AuditLog.Module.OTHER,
            action=AuditLog.Action.CREATE, message="حدث إداري.",
            target_type="test.Target", target_id="1", target_display="هدف",
        )
        snapshot = event.actor_display
        self.actor.delete()
        event.refresh_from_db()
        self.assertIsNone(event.actor)
        self.assertEqual(event.actor_display, snapshot)

    def test_transaction_rollback_removes_event(self):
        before = AuditLog.objects.count()
        try:
            with transaction.atomic():
                record_audit_event(
                    actor=self.actor, module=AuditLog.Module.OTHER,
                    action=AuditLog.Action.CREATE, message="لن يبقى.",
                    target_type="test.Target", target_id="1", target_display="هدف",
                )
                raise ValueError("rollback")
        except ValueError:
            pass
        self.assertEqual(AuditLog.objects.count(), before)


class AuditApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="audit-admin", password="Strong!934",
            role=User.Role.SCHOOL_ADMIN, must_change_password=False,
        )
        self.event = record_audit_event(
            actor=self.admin, module=AuditLog.Module.STUDENTS,
            action=AuditLog.Action.TRANSFER,
            message="نقل أحمد الطالب محمد.", target_type="students.Enrollment",
            target_id="enrollment-1", target_display="محمد أحمد",
        )

    def authenticate(self, user):
        self.client.force_authenticate(user, token={"client": "web"})

    def test_admin_list_retrieve_search_filters_and_ordering(self):
        self.authenticate(self.admin)
        older = record_audit_event(
            actor=self.admin, module=AuditLog.Module.ACCOUNTS,
            action=AuditLog.Action.CREATE, message="أنشأ حسابًا.",
            target_type="accounts.User", target_id="user-1", target_display="سارة",
        )
        AuditLog.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=2))
        listed = self.client.get("/api/v1/audit-logs/")
        self.assertEqual(listed.status_code, 200)
        ids = [row["id"] for row in listed.data["data"]["results"]]
        self.assertEqual(ids[0], str(self.event.id))
        self.assertEqual(self.client.get(f"/api/v1/audit-logs/{self.event.id}/").status_code, 200)
        self.assertEqual(len(self.client.get("/api/v1/audit-logs/?search=محمد").data["data"]["results"]), 1)
        self.assertEqual(len(self.client.get("/api/v1/audit-logs/?module=students&action=TRANSFER").data["data"]["results"]), 1)
        today = timezone.localdate().isoformat()
        self.assertEqual(len(self.client.get(f"/api/v1/audit-logs/?date_from={today}&date_to={today}").data["data"]["results"]), 1)

    def test_only_admin_and_superuser_can_read(self):
        self.authenticate(self.admin)
        self.assertEqual(self.client.get("/api/v1/audit-logs/").status_code, 200)
        root = User.objects.create_superuser(username="audit-root", password="Strong!934")
        self.authenticate(root)
        self.assertEqual(self.client.get("/api/v1/audit-logs/").status_code, 200)
        for role in (User.Role.SECRETARIAT, User.Role.SUPERVISOR, User.Role.TEACHER, User.Role.GUARDIAN, User.Role.TECH_SUPPORT):
            user = User.objects.create_user(username=f"audit-{role}", password="Strong!934", role=role, must_change_password=False)
            self.authenticate(user)
            self.assertEqual(self.client.get("/api/v1/audit-logs/").status_code, 403)

    def test_api_is_read_only(self):
        self.authenticate(self.admin)
        url = "/api/v1/audit-logs/"
        self.assertEqual(self.client.post(url, {}).status_code, 405)
        detail = f"{url}{self.event.id}/"
        self.assertEqual(self.client.put(detail, {}).status_code, 405)
        self.assertEqual(self.client.patch(detail, {}).status_code, 405)
        self.assertEqual(self.client.delete(detail).status_code, 405)


class AuditIntegrationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="business-admin", first_name="خالد", password="Strong!934",
            role=User.Role.SCHOOL_ADMIN, must_change_password=False,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin, token={"client": "web"})

    def test_user_create_role_change_noop_and_password_are_business_events(self):
        created = self.client.post("/api/v1/accounts/users/", {
            "username": "business-user", "first_name": "محمد", "last_name": "أحمد",
            "role": User.Role.TEACHER,
        }, format="json")
        self.assertEqual(created.status_code, 201)
        user = User.objects.get(username="business-user")
        self.assertEqual(AuditLog.objects.filter(target_id=str(user.id), action=AuditLog.Action.CREATE).count(), 1)
        self.client.patch(f"/api/v1/accounts/users/{user.id}/", {"role": User.Role.SUPERVISOR}, format="json")
        self.assertEqual(AuditLog.objects.filter(target_id=str(user.id), action=AuditLog.Action.CHANGE_ROLE).count(), 1)
        self.client.patch(f"/api/v1/accounts/users/{user.id}/", {"role": User.Role.SUPERVISOR}, format="json")
        self.assertEqual(AuditLog.objects.filter(target_id=str(user.id), action=AuditLog.Action.CHANGE_ROLE).count(), 1)
        response = self.client.post(f"/api/v1/accounts/users/{user.id}/reset-password/", {}, format="json")
        self.assertEqual(response.status_code, 200)
        password_log = AuditLog.objects.get(target_id=str(user.id), action=AuditLog.Action.RESET_PASSWORD)
        temporary_password = response.data["data"]["temporary_password"]
        self.assertNotIn(temporary_password, str(password_log.metadata))
        self.assertNotIn(temporary_password, password_log.message)

    def test_student_transfer_creates_one_specialized_and_one_general_event(self):
        year = AcademicYear.objects.create(start_date=date(2026, 9, 1), end_date=date(2027, 6, 30))
        grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="السابع")
        old = Section.objects.create(academic_year=year, grade_level=grade, name="أ")
        new = Section.objects.create(academic_year=year, grade_level=grade, name="ب")
        student = Student.objects.create(first_name="محمد", last_name="أحمد", birth_date=date(2014, 1, 1), gender=Student.Gender.MALE)
        enrollment = Enrollment.objects.create(student=student, academic_year=year, section=old, enrollment_date=date(2026, 9, 1))
        before = AuditLog.objects.count()
        transfer_student_between_sections(enrollment=enrollment, target_section=new, actor=self.admin)
        self.assertEqual(StudentAuditLog.objects.filter(enrollment=enrollment).count(), 1)
        self.assertEqual(AuditLog.objects.count(), before + 1)
        event = AuditLog.objects.latest("created_at")
        self.assertEqual(event.action, AuditLog.Action.TRANSFER)
        self.assertEqual(event.metadata, {"old_section": str(old), "new_section": str(new)})
        before = AuditLog.objects.count()
        with self.assertRaises(Exception):
            transfer_student_between_sections(enrollment=enrollment, target_section=new, actor=self.admin)
        self.assertEqual(AuditLog.objects.count(), before)

    def test_enrollment_create_has_one_general_event_and_no_finance_side_effect_event(self):
        year = AcademicYear.objects.create(start_date=date(2028, 9, 1), end_date=date(2029, 6, 30))
        grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="الثامن")
        section = Section.objects.create(academic_year=year, grade_level=grade, name="أ")
        GradeTuitionPlan.objects.create(
            academic_year=year, grade_level=grade,
            base_tuition_usd=Decimal("1000"), created_by=self.admin,
        )
        student = Student.objects.create(first_name="سارة", last_name="أحمد", birth_date=date(2015, 1, 1), gender=Student.Gender.FEMALE)
        before = AuditLog.objects.count()
        response = self.client.post("/api/v1/students/enrollments/", {
            "student": str(student.id), "academic_year": str(year.id),
            "section": str(section.id), "enrollment_date": "2028-09-01",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(AuditLog.objects.count(), before + 1)
        self.assertEqual(AuditLog.objects.latest("created_at").module, AuditLog.Module.STUDENTS)

    def test_grades_bulk_and_publish_create_single_non_noop_summaries(self):
        year = AcademicYear.objects.create(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        term = Term.objects.create(academic_year=year, number=Term.Number.FIRST, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="التاسع")
        section = Section.objects.create(academic_year=year, grade_level=grade, name="أ")
        subject = Subject.objects.create(name="الرياضيات")
        plan = GradeSubject.objects.create(academic_year=year, grade_level=grade, subject=subject)
        student = Student.objects.create(first_name="رامي", last_name="خالد", birth_date=date(2013, 1, 1), gender=Student.Gender.MALE)
        enrollment = Enrollment.objects.create(student=student, academic_year=year, section=section, enrollment_date=date(2026, 1, 1))
        assessment = create_assessment(section=section, grade_subject=plan, term=term, title="اختبار", max_score=Decimal("20"), assessment_date=date(2026, 2, 1), actor=self.admin)
        before = AuditLog.objects.count()
        records = [{"enrollment": enrollment, "score": Decimal("18")}]
        save_assessment_scores_bulk(assessment=assessment, section=section, records=records, actor=self.admin)
        self.assertEqual(AuditLog.objects.count(), before + 1)
        self.assertEqual(ScoreAuditLog.objects.count(), 1)
        save_assessment_scores_bulk(assessment=assessment, section=section, records=records, actor=self.admin)
        self.assertEqual(AuditLog.objects.count(), before + 1)
        publish_section_assessments(section=section, term=term, actor=self.admin)
        self.assertEqual(AuditLog.objects.filter(module=AuditLog.Module.GRADES, action=AuditLog.Action.PUBLISH).count(), 1)
        publish_section_assessments(section=section, term=term, actor=self.admin)
        self.assertEqual(AuditLog.objects.filter(module=AuditLog.Module.GRADES, action=AuditLog.Action.PUBLISH).count(), 1)

    def test_payment_audits_success_but_not_validation_failure(self):
        year = AcademicYear.objects.create(start_date=date(2029, 9, 1), end_date=date(2030, 6, 30))
        grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="العاشر")
        section = Section.objects.create(academic_year=year, grade_level=grade, name="أ")
        student = Student.objects.create(first_name="ليلى", last_name="عمر", birth_date=date(2012, 1, 1), gender=Student.Gender.FEMALE)
        enrollment = Enrollment.objects.create(student=student, academic_year=year, section=section, enrollment_date=date(2029, 9, 1))
        plan = GradeTuitionPlan.objects.create(academic_year=year, grade_level=grade, base_tuition_usd=Decimal("1000"), created_by=self.admin)
        account = StudentFinancialAccount.objects.create(enrollment=enrollment, tuition_plan=plan, created_by=self.admin)
        before = AuditLog.objects.count()
        record_payment(account=account, currency="usd", amount=Decimal("200"), actor=self.admin)
        self.assertEqual(AuditLog.objects.count(), before + 1)
        with self.assertRaises(Exception):
            record_payment(account=account, currency="usd", amount=Decimal("0"), actor=self.admin)
        self.assertEqual(AuditLog.objects.count(), before + 1)


class ZAuditMigrationPreservationTests(TransactionTestCase):
    reset_sequences = True

    def test_legacy_row_is_preserved_and_sanitized(self):
        actor = User.objects.create_user(
            username="legacy-actor", password="Strong!934",
            role=User.Role.SCHOOL_ADMIN, must_change_password=False,
        )
        executor = MigrationExecutor(connection)
        executor.migrate([("audit_logs", "0001_initial")])
        old_apps = executor.loader.project_state([("audit_logs", "0001_initial")]).apps
        OldAudit = old_apps.get_model("audit_logs", "AuditLog")
        entry_id = uuid4()
        entry = OldAudit.objects.create(
            id=entry_id, actor_id=actor.id, action="UPDATE",
            resource_type="students.Enrollment", resource_id="legacy-id",
            resource_display="محمد أحمد",
            changes={"section": "أ", "nested": {"refresh_token": "secret", "safe": True}},
        )
        created_at = entry.created_at
        executor = MigrationExecutor(connection)
        executor.migrate([("audit_logs", "0002_business_audit_log")])
        new_apps = executor.loader.project_state([("audit_logs", "0002_business_audit_log")]).apps
        NewAudit = new_apps.get_model("audit_logs", "AuditLog")
        migrated = NewAudit.objects.get(pk=entry_id)
        self.assertEqual(migrated.target_type, "students.Enrollment")
        self.assertEqual(migrated.target_id, "legacy-id")
        self.assertEqual(migrated.target_display, "محمد أحمد")
        self.assertEqual(migrated.metadata, {"section": "أ", "nested": {"safe": True}})
        self.assertEqual(migrated.actor_id, actor.id)
        self.assertEqual(migrated.actor_display, "legacy-actor")
        self.assertEqual(migrated.module, "students")
        self.assertTrue(migrated.message)
        self.assertEqual(migrated.created_at, created_at)
