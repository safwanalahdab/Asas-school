from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from academics.models import AcademicYear, GradeLevel, Section
from students.models import Enrollment, Student

from .models import GradeTuitionPlan, Payment, StudentDiscount, StudentFinancialAccount
from .services import calculate_account_totals


User = get_user_model()

LIST_URL = "/api/v1/finance/accounts/"
ACCOUNT_PERMISSION = "finance.view_studentfinancialaccount"
DISCOUNT_PERMISSION = "finance.view_studentdiscount"
PAYMENT_PERMISSION = "finance.view_payment"

# Columns only the full detail lists select; the totals prefetch never reads them.
DISCOUNT_DETAIL_COLUMN = '"finance_student_discount"."reason"'
PAYMENT_DETAIL_COLUMN = '"finance_payment"."note"'


class FinanceQueryPerformanceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = self.user("perf-admin", User.Role.SCHOOL_ADMIN)
        self.teacher = self.user("perf-teacher", User.Role.TEACHER)
        self.year = AcademicYear.objects.create(
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
            status=AcademicYear.Status.ACTIVE,
        )
        self.grade = GradeLevel.objects.create(stage=GradeLevel.Stage.PRIMARY, name="Perf")
        self.section = Section.objects.create(
            academic_year=self.year, grade_level=self.grade, name="A",
        )
        self.plan = GradeTuitionPlan.objects.create(
            academic_year=self.year, grade_level=self.grade,
            base_tuition_usd=Decimal("1000.00"), created_by=self.admin,
        )

    def user(self, username, role):
        return User.objects.create_user(
            username=username, password="StrongPass!123", role=role,
            must_change_password=False,
        )

    def grant(self, user, *codes):
        for code in codes:
            app, codename = code.split(".")
            user.user_permissions.add(Permission.objects.get(
                content_type__app_label=app, codename=codename,
            ))

    def account(self, name):
        student = Student.objects.create(
            first_name=name, last_name="Child", birth_date=date(2015, 1, 1),
            gender=Student.Gender.MALE,
        )
        enrollment = Enrollment.objects.create(
            student=student, academic_year=self.year, section=self.section,
            enrollment_date=date(2026, 1, 1),
        )
        return StudentFinancialAccount.objects.create(
            enrollment=enrollment, tuition_plan=self.plan, created_by=self.admin,
        )

    def add_records(self, account):
        """Active and cancelled rows of every kind; totals ignore cancelled ones."""
        now = timezone.now()
        cancelled = {
            "is_cancelled": True, "cancellation_reason": "Correction",
            "cancelled_by": self.admin, "cancelled_at": now,
        }
        discounts = [
            StudentDiscount.objects.create(
                account=account, discount_type=StudentDiscount.DiscountType.PERCENTAGE,
                value=Decimal("3.33"), created_by=self.admin,
            ),
            StudentDiscount.objects.create(
                account=account, discount_type=StudentDiscount.DiscountType.FIXED,
                value=Decimal("50.00"), currency="usd", equivalent_usd=Decimal("50.00"),
                created_by=self.admin,
            ),
            StudentDiscount.objects.create(
                account=account, discount_type=StudentDiscount.DiscountType.PERCENTAGE,
                value=Decimal("10.00"), created_by=self.admin, **cancelled,
            ),
        ]
        payments = [
            Payment.objects.create(
                account=account, currency="usd", amount=Decimal("100.00"),
                equivalent_usd=Decimal("100.00"), recorded_by=self.admin,
            ),
            Payment.objects.create(
                account=account, currency="syp", amount=Decimal("1000000.00"),
                exchange_rate_syp_per_usd=Decimal("13000.0000"),
                equivalent_usd=Decimal("76.92"), recorded_by=self.admin, note="SYP",
            ),
            Payment.objects.create(
                account=account, currency="usd", amount=Decimal("200.00"),
                equivalent_usd=Decimal("200.00"), recorded_by=self.admin, **cancelled,
            ),
        ]
        return discounts, payments

    def detail_url(self, account):
        return f"{LIST_URL}{account.pk}/"

    def get_with_queries(self, url, params=None):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url, params or {})
        self.assertEqual(response.status_code, 200)
        return response, ctx.captured_queries

    def expected_totals(self, account):
        """Totals from the unprefetched service path, i.e. the pre-change behavior."""
        totals = calculate_account_totals(
            StudentFinancialAccount.objects.get(pk=account.pk)
        )
        return {key: str(value) for key, value in totals.items()}

    def api_totals(self, totals):
        return {key: value for key, value in totals.items() if key != "payment_status"}

    def fetched(self, queries, column):
        return any(column in query["sql"] for query in queries)

    def test_list_query_count_does_not_grow_with_accounts(self):
        self.grant(self.teacher, ACCOUNT_PERMISSION)
        self.client.force_authenticate(self.teacher)
        self.add_records(self.account("Initial"))
        self.client.get(LIST_URL)

        _, small = self.get_with_queries(LIST_URL)
        for index in range(6):
            account = self.account(f"Extra{index}")
            self.add_records(account)
            self.add_records(account)
        response, large = self.get_with_queries(LIST_URL)

        self.assertEqual(response.data["data"]["count"], 7)
        self.assertEqual(len(large), len(small))

    def test_detail_query_count_does_not_grow_with_discounts_and_payments(self):
        self.grant(self.teacher, ACCOUNT_PERMISSION, DISCOUNT_PERMISSION, PAYMENT_PERMISSION)
        self.client.force_authenticate(self.teacher)
        account = self.account("Detail")
        self.add_records(account)
        self.client.get(self.detail_url(account))

        _, small = self.get_with_queries(self.detail_url(account))
        for _ in range(5):
            self.add_records(account)
        response, large = self.get_with_queries(self.detail_url(account))

        self.assertEqual(len(response.data["data"]["discounts"]), 18)
        self.assertEqual(len(response.data["data"]["payments"]), 18)
        self.assertEqual(len(large), len(small))

    def test_list_and_detail_totals_match_service_calculation(self):
        self.grant(self.teacher, ACCOUNT_PERMISSION)
        self.client.force_authenticate(self.teacher)
        partial = self.account("Partial")
        self.add_records(partial)
        empty = self.account("Empty")
        doubled = self.account("Doubled")
        self.add_records(doubled)
        self.add_records(doubled)

        results = self.client.get(LIST_URL).data["data"]["results"]
        for item in results:
            with self.subTest(account=item["student_display"]):
                account = StudentFinancialAccount.objects.get(pk=item["id"])
                self.assertEqual(self.api_totals(item["totals"]), self.expected_totals(account))
                detail = self.client.get(self.detail_url(account)).data["data"]
                self.assertEqual(detail["totals"], item["totals"])

        # Percentage rounding, SYP payments and cancelled rows, pinned explicitly.
        detail = self.client.get(self.detail_url(partial)).data["data"]
        self.assertEqual(detail["totals"], {
            "base_tuition_usd": "1000.00",
            "total_discounts_usd": "83.30",
            "net_tuition_usd": "916.70",
            "total_paid_usd": "176.92",
            "remaining_usd": "739.78",
            "payment_status": "partial",
        })
        self.assertEqual(
            self.client.get(self.detail_url(empty)).data["data"]["totals"]["payment_status"],
            "unpaid",
        )

    def test_account_permission_only_neither_fetches_nor_shows_details(self):
        self.grant(self.teacher, ACCOUNT_PERMISSION)
        self.client.force_authenticate(self.teacher)
        account = self.account("Restricted")
        self.add_records(account)

        response, queries = self.get_with_queries(self.detail_url(account))

        data = response.data["data"]
        self.assertNotIn("discounts", data)
        self.assertNotIn("payments", data)
        self.assertFalse(self.fetched(queries, DISCOUNT_DETAIL_COLUMN))
        self.assertFalse(self.fetched(queries, PAYMENT_DETAIL_COLUMN))
        self.assertEqual(self.api_totals(data["totals"]), self.expected_totals(account))

    def test_discount_permission_shows_only_discounts(self):
        self.grant(self.teacher, ACCOUNT_PERMISSION, DISCOUNT_PERMISSION)
        self.client.force_authenticate(self.teacher)
        account = self.account("Discounts")
        discounts, _ = self.add_records(account)

        response, queries = self.get_with_queries(self.detail_url(account))

        data = response.data["data"]
        self.assertEqual(
            {item["id"] for item in data["discounts"]},
            {str(discount.pk) for discount in discounts},
        )
        self.assertNotIn("payments", data)
        self.assertFalse(self.fetched(queries, PAYMENT_DETAIL_COLUMN))

    def test_payment_permission_shows_only_payments(self):
        self.grant(self.teacher, ACCOUNT_PERMISSION, PAYMENT_PERMISSION)
        self.client.force_authenticate(self.teacher)
        account = self.account("Payments")
        _, payments = self.add_records(account)

        response, queries = self.get_with_queries(self.detail_url(account))

        data = response.data["data"]
        self.assertEqual(
            {item["id"] for item in data["payments"]},
            {str(payment.pk) for payment in payments},
        )
        self.assertNotIn("discounts", data)
        self.assertFalse(self.fetched(queries, DISCOUNT_DETAIL_COLUMN))

    def test_all_view_permissions_show_complete_details(self):
        self.grant(self.teacher, ACCOUNT_PERMISSION, DISCOUNT_PERMISSION, PAYMENT_PERMISSION)
        self.client.force_authenticate(self.teacher)
        account = self.account("Complete")
        discounts, payments = self.add_records(account)

        data = self.client.get(self.detail_url(account)).data["data"]

        self.assertEqual(
            {item["id"] for item in data["discounts"]},
            {str(discount.pk) for discount in discounts},
        )
        self.assertEqual(
            {item["id"] for item in data["payments"]},
            {str(payment.pk) for payment in payments},
        )
        by_id = {item["id"]: item for item in data["discounts"]}
        self.assertEqual(by_id[str(discounts[0].pk)]["discount_usd"], "33.30")
        self.assertEqual(by_id[str(discounts[2].pk)]["cancelled_by_username"], self.admin.username)

    def test_superuser_sees_complete_details(self):
        root = User.objects.create_superuser(username="perf-root", password="StrongPass!123")
        self.client.force_authenticate(root)
        account = self.account("Root")
        discounts, payments = self.add_records(account)

        data = self.client.get(self.detail_url(account)).data["data"]

        self.assertEqual(len(data["discounts"]), len(discounts))
        self.assertEqual(len(data["payments"]), len(payments))
        self.assertEqual(self.api_totals(data["totals"]), self.expected_totals(account))
        self.assertEqual(self.client.get(LIST_URL).data["data"]["count"], 1)

    def test_account_without_discounts_or_payments_returns_zero_totals(self):
        self.grant(self.teacher, ACCOUNT_PERMISSION, DISCOUNT_PERMISSION, PAYMENT_PERMISSION)
        self.client.force_authenticate(self.teacher)
        account = self.account("Empty")
        expected = {
            "base_tuition_usd": "1000.00",
            "total_discounts_usd": "0.00",
            "net_tuition_usd": "1000.00",
            "total_paid_usd": "0.00",
            "remaining_usd": "1000.00",
            "payment_status": "unpaid",
        }

        listed = self.client.get(LIST_URL).data["data"]["results"][0]
        detail = self.client.get(self.detail_url(account)).data["data"]

        self.assertEqual(listed["totals"], expected)
        self.assertEqual(detail["totals"], expected)
        self.assertEqual(detail["discounts"], [])
        self.assertEqual(detail["payments"], [])

    def test_pagination_ordering_and_filters_are_unchanged(self):
        self.grant(self.teacher, ACCOUNT_PERMISSION)
        self.client.force_authenticate(self.teacher)
        partial = self.account("Alpha")
        self.add_records(partial)
        unpaid = self.account("Bravo")
        paid = self.account("Charlie")
        Payment.objects.create(
            account=paid, currency="usd", amount=Decimal("1000.00"),
            equivalent_usd=Decimal("1000.00"), recorded_by=self.admin,
        )

        first_page = self.client.get(LIST_URL, {"page_size": 2}).data["data"]
        second_page = self.client.get(LIST_URL, {"page_size": 2, "page": 2}).data["data"]
        self.assertEqual(first_page["count"], 3)
        self.assertIsNotNone(first_page["next"])
        self.assertEqual(
            [item["id"] for item in first_page["results"] + second_page["results"]],
            [str(partial.pk), str(unpaid.pk), str(paid.pk)],
        )

        for status_value, account in (("partial", partial), ("unpaid", unpaid), ("paid", paid)):
            with self.subTest(payment_status=status_value):
                results = self.client.get(LIST_URL, {"payment_status": status_value}).data["data"]["results"]
                self.assertEqual([item["id"] for item in results], [str(account.pk)])
                self.assertEqual(results[0]["totals"]["payment_status"], status_value)

        results = self.client.get(LIST_URL, {"search": "Brav"}).data["data"]["results"]
        self.assertEqual([item["id"] for item in results], [str(unpaid.pk)])
