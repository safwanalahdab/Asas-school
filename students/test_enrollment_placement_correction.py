from datetime import date

from django.test import TestCase
from django.utils import timezone
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
    Term,
)
from attendance.models import AttendanceRecord, AttendanceSheet
from behavior.models import BehaviorNote, StudentPointEntry
from finance.models import (
    GradeTuitionPlan,
    Payment,
    StudentDiscount,
    StudentFinancialAccount,
)
from grades.models import Assessment, StudentScore

from .models import (
    Enrollment,
    Student,
    StudentAuditLog,
    StudentImportJob,
    StudentImportRow,
)


class EnrollmentPlacementCorrectionTests(TestCase):
    def setUp(self):
        self.year = AcademicYear.objects.create(
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            status=AcademicYear.Status.ACTIVE,
        )
        self.other_year = AcademicYear.objects.create(
            start_date=date(2027, 9, 1),
            end_date=date(2028, 6, 30),
        )
        self.grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY,
            name="الخامس",
        )
        self.other_grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.SECONDARY,
            name="العاشر",
        )
        self.section_a = Section.objects.create(
            academic_year=self.year,
            grade_level=self.grade,
            name="أ",
        )
        self.section_b = Section.objects.create(
            academic_year=self.year,
            grade_level=self.grade,
            name="ب",
        )
        self.other_grade_section = Section.objects.create(
            academic_year=self.year,
            grade_level=self.other_grade,
            name="أ",
        )
        self.other_year_section = Section.objects.create(
            academic_year=self.other_year,
            grade_level=self.grade,
            name="أ",
        )
        self.student = Student.objects.create(
            first_name="أحمد",
            last_name="خالد",
            birth_date=date(2016, 2, 1),
            gender=Student.Gender.MALE,
        )
        self.enrollment = Enrollment.objects.create(
            student=self.student,
            academic_year=self.year,
            section=self.section_a,
            enrollment_date=date(2026, 9, 1),
        )
        self.admin = self.user("placement-admin", User.Role.SCHOOL_ADMIN)
        self.supervisor = self.user("placement-supervisor", User.Role.SUPERVISOR)
        scope = SupervisorScope.objects.create(
            supervisor=self.supervisor,
            scope_type=SupervisorScope.ScopeType.SELECTED_STAGES,
        )
        SupervisorScopeStage.objects.create(
            scope=scope,
            stage=GradeLevel.Stage.PRIMARY,
        )
        self.url = (
            f"/api/v1/students/enrollments/{self.enrollment.pk}/correct-placement/"
        )

    @staticmethod
    def user(username, role):
        return User.objects.create_user(
            username=username,
            password="Strong!934",
            role=role,
            must_change_password=False,
        )

    @staticmethod
    def client_for(user):
        client = APIClient()
        client.force_authenticate(user, token={"client": "web"})
        return client

    def correct(self, user=None, section=None, reason="خطأ في إدخال الشعبة"):
        return self.client_for(user or self.admin).post(
            self.url,
            {
                "section": str((section or self.section_b).pk),
                "reason": reason,
            },
            format="json",
        )

    def assert_section_unchanged(self):
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.section_id, self.section_a.pk)

    def create_financial_account(self):
        plan = GradeTuitionPlan.objects.create(
            academic_year=self.year,
            grade_level=self.grade,
            base_tuition_usd="1000.00",
            created_by=self.admin,
        )
        account = StudentFinancialAccount.objects.create(
            enrollment=self.enrollment,
            tuition_plan=plan,
            created_by=self.admin,
        )
        return account, plan

    def create_target_tuition_plan(self):
        return GradeTuitionPlan.objects.create(
            academic_year=self.year,
            grade_level=self.other_grade,
            base_tuition_usd="1500.00",
            created_by=self.admin,
        )

    def create_payment(self, account, *, cancelled=False):
        payment_data = {
            "account": account,
            "currency": "usd",
            "amount": "100.00",
            "equivalent_usd": "100.00",
            "recorded_by": self.admin,
        }
        if cancelled:
            payment_data.update(
                is_cancelled=True,
                cancellation_reason="إلغاء الدفعة",
                cancelled_by=self.admin,
                cancelled_at=timezone.now(),
            )
        return Payment.objects.create(**payment_data)

    def test_school_admin_can_correct_placement(self):
        response = self.correct()
        self.assertEqual(response.status_code, 200)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.section_id, self.section_b.pk)

    def test_supervisor_can_correct_when_current_and_target_are_in_scope(self):
        response = self.correct(user=self.supervisor)
        self.assertEqual(response.status_code, 200)

    def test_supervisor_cannot_correct_when_current_section_is_outside_scope(self):
        outside_student = Student.objects.create(
            first_name="خارج",
            last_name="النطاق",
            birth_date=date(2010, 1, 1),
            gender=Student.Gender.FEMALE,
        )
        outside = Enrollment.objects.create(
            student=outside_student,
            academic_year=self.year,
            section=self.other_grade_section,
            enrollment_date=date(2026, 9, 1),
        )
        response = self.client_for(self.supervisor).post(
            f"/api/v1/students/enrollments/{outside.pk}/correct-placement/",
            {"section": str(self.section_b.pk), "reason": "تصحيح"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_supervisor_cannot_correct_to_target_outside_scope(self):
        response = self.correct(
            user=self.supervisor,
            section=self.other_grade_section,
        )
        self.assertEqual(response.status_code, 403)
        self.assert_section_unchanged()

    def test_unauthorized_roles_do_not_receive_correction_permission(self):
        for role in (
            User.Role.SECRETARIAT,
            User.Role.TEACHER,
            User.Role.GUARDIAN,
            User.Role.TECH_SUPPORT,
        ):
            with self.subTest(role=role):
                user = self.user(f"placement-{role}", role)
                self.assertFalse(
                    user.has_perm("students.correct_enrollment_placement")
                )
                self.assertEqual(self.correct(user=user).status_code, 403)
                self.assert_section_unchanged()

    def test_same_section_is_rejected(self):
        self.assertEqual(self.correct(section=self.section_a).status_code, 400)

    def test_cross_grade_correction_without_financial_account_succeeds(self):
        original_academic_year_id = self.enrollment.academic_year_id

        response = self.correct(section=self.other_grade_section)

        self.assertEqual(response.status_code, 200)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.section_id, self.other_grade_section.pk)
        self.assertEqual(
            self.enrollment.section.grade_level_id,
            self.other_grade.pk,
        )
        self.assertEqual(
            self.enrollment.academic_year_id,
            original_academic_year_id,
        )

    def test_different_academic_year_is_rejected(self):
        self.assertEqual(
            self.correct(section=self.other_year_section).status_code,
            400,
        )

    def test_missing_and_blank_reason_are_rejected(self):
        client = self.client_for(self.admin)
        missing = client.post(
            self.url,
            {"section": str(self.section_b.pk)},
            format="json",
        )
        blank = self.correct(reason="   ")
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(blank.status_code, 400)

    def test_normal_patch_cannot_change_section_or_academic_year(self):
        url = f"/api/v1/students/enrollments/{self.enrollment.pk}/"
        client = self.client_for(self.admin)
        section = client.patch(
            url,
            {"section": str(self.section_b.pk)},
            format="json",
        )
        academic_year = client.patch(
            url,
            {"academic_year": str(self.other_year.pk)},
            format="json",
        )
        self.assertEqual(section.status_code, 400)
        self.assertEqual(academic_year.status_code, 400)
        self.assert_section_unchanged()

    def test_normal_patch_keeps_other_existing_fields_writable(self):
        response = self.client_for(self.admin).patch(
            f"/api/v1/students/enrollments/{self.enrollment.pk}/",
            {"usual_arrival_method": Enrollment.TransportationMethod.GUARDIAN},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.enrollment.refresh_from_db()
        self.assertEqual(
            self.enrollment.usual_arrival_method,
            Enrollment.TransportationMethod.GUARDIAN,
        )

    def test_attendance_record_blocks_correction(self):
        sheet = AttendanceSheet.objects.create(
            section=self.section_a,
            attendance_date=date(2026, 9, 2),
            created_by=self.admin,
        )
        AttendanceRecord.objects.create(sheet=sheet, enrollment=self.enrollment)
        self.assertEqual(self.correct().status_code, 400)
        self.assert_section_unchanged()

    def test_student_score_blocks_correction(self):
        subject = Subject.objects.create(name="رياضيات التصحيح")
        grade_subject = GradeSubject.objects.create(
            academic_year=self.year,
            grade_level=self.grade,
            subject=subject,
        )
        term = Term.objects.create(
            academic_year=self.year,
            number=Term.Number.FIRST,
            start_date=date(2026, 9, 1),
            end_date=date(2027, 1, 31),
        )
        assessment = Assessment.objects.create(
            grade_subject=grade_subject,
            term=term,
            title="اختبار",
            max_score=100,
            assessment_date=date(2026, 10, 1),
            created_by=self.admin,
        )
        StudentScore.objects.create(
            assessment=assessment,
            enrollment=self.enrollment,
            recorded_section=self.section_a,
            score=80,
            updated_by=self.admin,
        )
        self.assertEqual(self.correct().status_code, 400)
        self.assert_section_unchanged()

    def test_previous_section_transfer_blocks_correction(self):
        StudentAuditLog.objects.create(
            event_type=StudentAuditLog.EventType.SECTION_TRANSFER,
            actor=self.admin,
            enrollment=self.enrollment,
            old_section=self.section_b,
            new_section=self.section_a,
        )
        self.assertEqual(self.correct().status_code, 400)
        self.assert_section_unchanged()

    def test_behavior_note_and_point_entry_do_not_block_correction(self):
        BehaviorNote.objects.create(
            enrollment=self.enrollment,
            note_type=BehaviorNote.Type.POSITIVE,
            title="ملاحظة",
            description="وصف",
            occurred_on=date(2026, 9, 2),
            created_by=self.admin,
        )
        StudentPointEntry.objects.create(
            enrollment=self.enrollment,
            points=10,
            note="مشاركة",
            occurred_on=date(2026, 9, 2),
            created_by=self.admin,
        )
        self.assertEqual(self.correct().status_code, 200)

    def test_same_grade_correction_does_not_change_financial_plan(self):
        account, plan = self.create_financial_account()
        self.assertEqual(self.correct().status_code, 200)
        account.refresh_from_db()
        self.assertEqual(account.tuition_plan_id, plan.pk)

    def test_cross_grade_correction_updates_existing_financial_account_plan(self):
        account, _ = self.create_financial_account()
        target_plan = self.create_target_tuition_plan()

        response = self.correct(section=self.other_grade_section)

        self.assertEqual(response.status_code, 200)
        self.enrollment.refresh_from_db()
        account.refresh_from_db()
        self.assertEqual(self.enrollment.section_id, self.other_grade_section.pk)
        self.assertEqual(account.tuition_plan_id, target_plan.pk)

    def test_cross_grade_correction_preserves_percentage_discount(self):
        account, _ = self.create_financial_account()
        target_plan = self.create_target_tuition_plan()
        discount = StudentDiscount.objects.create(
            account=account,
            discount_type=StudentDiscount.DiscountType.PERCENTAGE,
            value="10.00",
            reason="حسم أخوة",
            created_by=self.admin,
        )

        response = self.correct(section=self.other_grade_section)

        self.assertEqual(response.status_code, 200)
        account.refresh_from_db()
        discount.refresh_from_db()
        self.assertEqual(account.tuition_plan_id, target_plan.pk)
        self.assertEqual(discount.value, 10)
        self.assertEqual(discount.reason, "حسم أخوة")
        self.assertFalse(discount.is_cancelled)

    def test_cross_grade_correction_preserves_active_fixed_discount(self):
        account, _ = self.create_financial_account()
        target_plan = self.create_target_tuition_plan()
        discount = StudentDiscount.objects.create(
            account=account,
            discount_type=StudentDiscount.DiscountType.FIXED,
            value="100.00",
            currency="usd",
            equivalent_usd="100.00",
            reason="حسم ثابت فعال",
            created_by=self.admin,
        )

        response = self.correct(section=self.other_grade_section)

        self.assertEqual(response.status_code, 200)
        self.enrollment.refresh_from_db()
        account.refresh_from_db()
        discount.refresh_from_db()
        self.assertEqual(self.enrollment.section_id, self.other_grade_section.pk)
        self.assertEqual(account.tuition_plan_id, target_plan.pk)
        self.assertTrue(StudentDiscount.objects.filter(pk=discount.pk).exists())
        self.assertEqual(
            discount.discount_type,
            StudentDiscount.DiscountType.FIXED,
        )
        self.assertEqual(discount.value, 100)
        self.assertFalse(discount.is_cancelled)
        self.assertTrue(
            StudentAuditLog.objects.filter(
                enrollment=self.enrollment,
                event_type=StudentAuditLog.EventType.PLACEMENT_CORRECTION,
                old_section=self.section_a,
                new_section=self.other_grade_section,
            ).exists()
        )

    def test_cross_grade_correction_preserves_cancelled_fixed_discount(self):
        account, _ = self.create_financial_account()
        target_plan = self.create_target_tuition_plan()
        discount = StudentDiscount.objects.create(
            account=account,
            discount_type=StudentDiscount.DiscountType.FIXED,
            value="100.00",
            currency="usd",
            equivalent_usd="100.00",
            reason="حسم ثابت",
            created_by=self.admin,
            is_cancelled=True,
            cancellation_reason="إلغاء الحسم",
            cancelled_by=self.admin,
            cancelled_at=timezone.now(),
        )

        response = self.correct(section=self.other_grade_section)

        self.assertEqual(response.status_code, 200)
        account.refresh_from_db()
        discount.refresh_from_db()
        self.assertEqual(account.tuition_plan_id, target_plan.pk)
        self.assertEqual(discount.value, 100)
        self.assertEqual(discount.reason, "حسم ثابت")
        self.assertTrue(discount.is_cancelled)
        self.assertEqual(discount.cancellation_reason, "إلغاء الحسم")

    def test_cross_grade_correction_with_payment_is_rejected_atomically(self):
        account, old_plan = self.create_financial_account()
        self.create_target_tuition_plan()
        self.create_payment(account)

        response = self.correct(section=self.other_grade_section)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["code"],
            "ENROLLMENT_CORRECTION_HAS_PAYMENTS",
        )
        self.assert_section_unchanged()
        account.refresh_from_db()
        self.assertEqual(account.tuition_plan_id, old_plan.pk)
        self.assertFalse(
            StudentAuditLog.objects.filter(
                enrollment=self.enrollment,
                event_type=StudentAuditLog.EventType.PLACEMENT_CORRECTION,
            ).exists()
        )

    def test_cross_grade_correction_with_cancelled_payment_is_rejected(self):
        account, old_plan = self.create_financial_account()
        self.create_target_tuition_plan()
        self.create_payment(account, cancelled=True)

        response = self.correct(section=self.other_grade_section)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["code"],
            "ENROLLMENT_CORRECTION_HAS_PAYMENTS",
        )
        self.assert_section_unchanged()
        account.refresh_from_db()
        self.assertEqual(account.tuition_plan_id, old_plan.pk)
        self.assertFalse(
            StudentAuditLog.objects.filter(
                enrollment=self.enrollment,
                event_type=StudentAuditLog.EventType.PLACEMENT_CORRECTION,
            ).exists()
        )

    def test_cross_grade_correction_without_target_plan_is_rejected_atomically(self):
        account, old_plan = self.create_financial_account()

        response = self.correct(section=self.other_grade_section)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["code"],
            "TARGET_GRADE_TUITION_PLAN_NOT_FOUND",
        )
        self.assert_section_unchanged()
        account.refresh_from_db()
        self.assertEqual(account.tuition_plan_id, old_plan.pk)
        self.assertFalse(
            StudentAuditLog.objects.filter(
                enrollment=self.enrollment,
                event_type=StudentAuditLog.EventType.PLACEMENT_CORRECTION,
            ).exists()
        )

    def test_student_import_row_does_not_block_correction(self):
        job = StudentImportJob.objects.create(
            created_by=self.admin,
            original_filename="students.xlsx",
            file_sha256="0" * 64,
            file_size=1,
        )
        StudentImportRow.objects.create(
            job=job,
            row_number=2,
            enrollment=self.enrollment,
        )
        self.assertEqual(self.correct().status_code, 200)

    def test_success_creates_exact_placement_correction_audit(self):
        reason = "تم اختيار الشعبة أ بدل ب"
        self.assertEqual(self.correct(reason=reason).status_code, 200)
        audit = StudentAuditLog.objects.get(enrollment=self.enrollment)
        self.assertEqual(
            audit.event_type,
            StudentAuditLog.EventType.PLACEMENT_CORRECTION,
        )
        self.assertEqual(audit.actor, self.admin)
        self.assertEqual(audit.enrollment, self.enrollment)
        self.assertEqual(audit.old_section, self.section_a)
        self.assertEqual(audit.new_section, self.section_b)
        self.assertEqual(audit.reason, reason)

    def test_existing_transfer_behavior_remains_unchanged(self):
        response = self.client_for(self.admin).post(
            f"/api/v1/students/enrollments/{self.enrollment.pk}/transfer/",
            {"section": str(self.section_b.pk)},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        audit = StudentAuditLog.objects.get(enrollment=self.enrollment)
        self.assertEqual(audit.event_type, StudentAuditLog.EventType.SECTION_TRANSFER)
        self.assertEqual(audit.reason, "")

    def test_transfer_still_rejects_different_grade(self):
        response = self.client_for(self.admin).post(
            f"/api/v1/students/enrollments/{self.enrollment.pk}/transfer/",
            {"section": str(self.other_grade_section.pk)},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "SECTION_GRADE_MISMATCH")
        self.assert_section_unchanged()
