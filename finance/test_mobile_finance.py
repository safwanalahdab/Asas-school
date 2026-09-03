from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from academics.models import AcademicYear, GradeLevel, Section
from audit_logs.models import AuditLog
from notifications.models import Notification
from students.models import Enrollment, GuardianStudent, Student

from .models import (
    GradeTuitionPlan,
    MoneyCurrency,
    Payment,
    StudentDiscount,
    StudentFinancialAccount,
)
from .services import (
    cancel_payment,
    create_student_discount,
    ensure_financial_account_for_enrollment,
    record_payment,
)


User = get_user_model()


class MobileFinanceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.guardian = self.make_user("finance-guardian", User.Role.GUARDIAN)
        self.other_guardian = self.make_user("finance-other", User.Role.GUARDIAN)
        self.staff = self.make_user("finance-staff", User.Role.SCHOOL_ADMIN)
        self.year = self.make_year(2026, AcademicYear.Status.ACTIVE)
        self.old_year = self.make_year(2025, AcademicYear.Status.CLOSED)
        self.grade = GradeLevel.objects.create(
            stage=GradeLevel.Stage.PRIMARY, name="Finance Grade",
        )
        self.section = Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name="A",
        )
        self.old_section = Section.objects.create(
            academic_year=self.old_year, grade_level=self.grade, name="Old",
        )
        self.child = self.make_child("Owned", self.guardian)
        self.other_child = self.make_child("Other", self.other_guardian)
        self.enrollment = Enrollment.objects.create(
            student=self.child, academic_year=self.year, section=self.section,
            enrollment_date=date(2026, 1, 1),
        )
        self.old_enrollment = Enrollment.objects.create(
            student=self.child, academic_year=self.old_year, section=self.old_section,
            enrollment_date=date(2025, 1, 1),
        )
        self.plan = GradeTuitionPlan.objects.create(
            academic_year=self.year, grade_level=self.grade,
            base_tuition_usd=Decimal("1000.00"), created_by=self.staff,
        )

    def make_user(self, username, role):
        return User.objects.create_user(
            username=username, password="StrongPass!493", role=role,
            must_change_password=False,
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
        return f"/api/v1/mobile/children/{(child or self.child).id}/finance/"

    def authenticate(self, client="mobile"):
        token = RefreshToken.for_user(self.guardian)
        token["client"] = client
        token["token_version"] = self.guardian.token_version
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    def make_account(self, enrollment=None, plan=None):
        return StudentFinancialAccount.objects.create(
            enrollment=enrollment or self.enrollment,
            tuition_plan=plan or self.plan,
            created_by=self.staff,
        )

    def add_discount(self, account, kind, value, **kwargs):
        return StudentDiscount.objects.create(
            account=account, discount_type=kind, value=Decimal(value),
            created_by=self.staff, **kwargs,
        )

    def add_payment(self, account, currency, amount, equivalent, **kwargs):
        return Payment.objects.create(
            account=account, currency=currency, amount=Decimal(amount),
            equivalent_usd=Decimal(equivalent), recorded_by=self.staff, **kwargs,
        )

    def test_record_payment_notifies_once_and_cancellation_does_not_notify(self):
        account = self.make_account()
        payment = record_payment(
            account=account, currency=MoneyCurrency.USD,
            amount=Decimal("125.00"), actor=self.staff,
        )
        notification = Notification.objects.get()
        self.assertEqual(notification.recipient, self.guardian)
        self.assertEqual(notification.student, self.child)
        self.assertEqual(notification.resource_id, payment.id)
        self.assertEqual(
            notification.event_key, f"finance:payment:{payment.id}:created",
        )
        for private_value in ("125", "USD", "usd"):
            self.assertNotIn(private_value, notification.body)
        cancel_payment(
            payment=payment, actor=self.staff, cancellation_reason="correction",
        )
        self.assertEqual(Notification.objects.count(), 1)

    def test_account_assignment_and_discount_do_not_notify(self):
        account = ensure_financial_account_for_enrollment(
            enrollment=self.enrollment, actor=self.staff,
        )
        create_student_discount(
            account=account,
            discount_type=StudentDiscount.DiscountType.PERCENTAGE,
            value=Decimal("5.00"),
            actor=self.staff,
        )
        self.assertFalse(Notification.objects.exists())

    def test_payment_without_guardian_link_succeeds_without_notification(self):
        child = Student.objects.create(
            first_name="No", last_name="Guardian", birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )
        enrollment = Enrollment.objects.create(
            student=child, academic_year=self.year, section=self.section,
            enrollment_date=date(2026, 1, 1),
        )
        account = self.make_account(enrollment=enrollment)
        payment = record_payment(
            account=account, currency=MoneyCurrency.USD,
            amount=Decimal("50.00"), actor=self.staff,
        )
        self.assertIsNotNone(payment.pk)
        self.assertFalse(Notification.objects.exists())

    @override_settings(FIREBASE_PUSH_ENABLED=True)
    @patch("notifications.push_services.send_notification_push", side_effect=RuntimeError("firebase down"))
    def test_firebase_failure_does_not_break_payment(self, _send):
        account = self.make_account()
        with self.captureOnCommitCallbacks(execute=True):
            payment = record_payment(
                account=account, currency=MoneyCurrency.USD,
                amount=Decimal("75.00"), actor=self.staff,
            )
        self.assertIsNotNone(payment.pk)
        self.assertEqual(Notification.objects.count(), 1)

    def test_configured_account_uses_services_and_historical_values(self):
        account = self.make_account()
        percentage = self.add_discount(
            account, StudentDiscount.DiscountType.PERCENTAGE, "10.00",
        )
        fixed_usd = self.add_discount(
            account, StudentDiscount.DiscountType.FIXED, "50.00",
            currency=MoneyCurrency.USD, equivalent_usd=Decimal("50.00"),
        )
        fixed_syp = self.add_discount(
            account, StudentDiscount.DiscountType.FIXED, "650000.00",
            currency=MoneyCurrency.SYP,
            exchange_rate_syp_per_usd=Decimal("13000.0000"),
            equivalent_usd=Decimal("50.00"),
        )
        usd = self.add_payment(account, MoneyCurrency.USD, "200.00", "200.00")
        syp = self.add_payment(
            account, MoneyCurrency.SYP, "1300000.00", "100.00",
            exchange_rate_syp_per_usd=Decimal("13000.0000"),
        )
        self.authenticate()
        response = self.client.get(self.url())
        data = response.data["data"]
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["account_configured"])
        self.assertEqual(data["summary"], {
            "currency": "USD", "base_tuition_usd": "1000.00",
            "total_discounts_usd": "200.00", "net_tuition_usd": "800.00",
            "total_paid_usd": "300.00", "remaining_usd": "500.00",
            "payment_status": "partial",
        })
        discounts = {item["id"]: item for item in data["discounts"]}
        self.assertEqual(discounts[str(percentage.id)]["discount_usd"], "100.00")
        self.assertEqual(discounts[str(fixed_usd.id)]["discount_usd"], "50.00")
        self.assertEqual(discounts[str(fixed_syp.id)]["discount_usd"], "50.00")
        payments = {item["id"]: item for item in data["payments"]}
        self.assertIsNone(payments[str(usd.id)]["exchange_rate_syp_per_usd"])
        self.assertEqual(payments[str(syp.id)]["amount"], "1300000.00")
        self.assertEqual(payments[str(syp.id)]["exchange_rate_syp_per_usd"], "13000.0000")
        self.assertEqual(payments[str(syp.id)]["equivalent_usd"], "100.00")

    def test_cancelled_entries_are_visible_but_excluded_from_totals(self):
        account = self.make_account()
        cancelled_at = timezone.now()
        discount = self.add_discount(
            account, StudentDiscount.DiscountType.FIXED, "100.00",
            currency=MoneyCurrency.USD, equivalent_usd=Decimal("100.00"),
            is_cancelled=True, cancellation_reason="Cancelled",
            cancelled_by=self.staff, cancelled_at=cancelled_at,
        )
        payment = self.add_payment(
            account, MoneyCurrency.USD, "250.00", "250.00",
            is_cancelled=True, cancellation_reason="Cancelled",
            cancelled_by=self.staff, cancelled_at=cancelled_at,
        )
        self.authenticate()
        data = self.client.get(self.url()).data["data"]
        self.assertEqual(data["summary"]["total_discounts_usd"], "0.00")
        self.assertEqual(data["summary"]["total_paid_usd"], "0.00")
        self.assertTrue(next(x for x in data["discounts"] if x["id"] == str(discount.id))["is_cancelled"])
        self.assertTrue(next(x for x in data["payments"] if x["id"] == str(payment.id))["is_cancelled"])

    def test_payment_status_unpaid_paid_and_negative_remaining(self):
        account = self.make_account()
        self.authenticate()
        self.assertEqual(self.client.get(self.url()).data["data"]["summary"]["payment_status"], "unpaid")
        payment = self.add_payment(account, MoneyCurrency.USD, "1100.00", "1100.00")
        summary = self.client.get(self.url()).data["data"]["summary"]
        self.assertEqual(summary["payment_status"], "paid")
        self.assertEqual(summary["remaining_usd"], "-100.00")
        payment.delete()

    def test_no_enrollment_and_no_account_contracts_have_no_side_effects(self):
        no_enrollment = self.make_child("NoEnrollment", self.guardian)
        self.authenticate()
        accounts_before = StudentFinancialAccount.objects.count()
        audits_before = AuditLog.objects.count()
        no_enrollment_data = self.client.get(self.url(no_enrollment)).data["data"]
        no_account_data = self.client.get(self.url()).data["data"]
        self.assertIsNone(no_enrollment_data["academic_year"])
        self.assertFalse(no_enrollment_data["account_configured"])
        self.assertIsNotNone(no_account_data["academic_year"])
        for data in (no_enrollment_data, no_account_data):
            self.assertIsNone(data["summary"])
            self.assertEqual(data["discounts"], [])
            self.assertEqual(data["payments"], [])
        self.assertEqual(StudentFinancialAccount.objects.count(), accounts_before)
        self.assertEqual(AuditLog.objects.count(), audits_before)

    def test_only_current_year_account_and_own_student_are_exposed(self):
        old_plan = GradeTuitionPlan.objects.create(
            academic_year=self.old_year, grade_level=self.grade,
            base_tuition_usd=Decimal("700.00"), created_by=self.staff,
        )
        old_account = self.make_account(self.old_enrollment, old_plan)
        self.add_payment(old_account, MoneyCurrency.USD, "100.00", "100.00")
        self.make_account()
        self.authenticate()
        data = self.client.get(self.url()).data["data"]
        self.assertEqual(data["summary"]["base_tuition_usd"], "1000.00")
        self.assertEqual(data["payments"], [])
        self.assertEqual(self.client.get(self.url(self.other_child)).status_code, 404)

    def test_ordering_and_admin_fields_are_not_exposed(self):
        account = self.make_account()
        first = self.add_payment(account, MoneyCurrency.USD, "10.00", "10.00")
        second = self.add_payment(account, MoneyCurrency.USD, "20.00", "20.00")
        now = timezone.now()
        Payment.objects.filter(pk=first.pk).update(paid_at=now - timedelta(days=1))
        Payment.objects.filter(pk=second.pk).update(paid_at=now)
        self.add_discount(
            account, StudentDiscount.DiscountType.PERCENTAGE, "5.00",
            reason="Sibling",
        )
        self.authenticate()
        data = self.client.get(self.url()).data["data"]
        self.assertEqual([x["id"] for x in data["payments"]], [str(second.id), str(first.id)])

        def keys(value):
            if isinstance(value, dict):
                return set(value) | set().union(*(keys(v) for v in value.values()))
            if isinstance(value, list):
                return set().union(*(keys(v) for v in value)) if value else set()
            return set()

        forbidden = {
            "created_by", "created_by_username", "recorded_by",
            "recorded_by_username", "cancelled_by", "cancelled_by_username",
            "cancellation_reason", "enrollment", "financial_account", "audit_log",
        }
        self.assertTrue(forbidden.isdisjoint(keys(data)))

    def test_authentication_password_gate_and_read_only(self):
        self.authenticate()
        for method in ("post", "put", "patch", "delete"):
            self.assertEqual(getattr(self.client, method)(self.url(), {}).status_code, 405)
        self.client.credentials()
        self.assertEqual(self.client.get(self.url()).status_code, 401)
        self.authenticate(client="web")
        self.assertEqual(self.client.get(self.url()).status_code, 401)
        self.guardian.must_change_password = True
        self.guardian.save(update_fields=["must_change_password"])
        self.authenticate()
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_inactive_guardian_is_rejected(self):
        token = RefreshToken.for_user(self.guardian)
        token["client"] = "mobile"
        token["token_version"] = self.guardian.token_version
        self.guardian.is_active = False
        self.guardian.save(update_fields=["is_active"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        self.assertEqual(self.client.get(self.url()).status_code, 401)
