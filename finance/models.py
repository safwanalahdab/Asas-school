import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from academics.models import AcademicYear, GradeLevel
from students.models import Enrollment


class MoneyCurrency(models.TextChoices):
    USD = "usd", "دولار أمريكي"
    SYP = "syp", "ليرة سورية"


class GradeTuitionPlan(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,
        related_name="tuition_plans",
    )

    grade_level = models.ForeignKey(
        GradeLevel,
        on_delete=models.PROTECT,
        related_name="tuition_plans",
    )

    base_tuition_usd = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_tuition_plans",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "finance_grade_tuition_plan"

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "academic_year",
                    "grade_level",
                ],
                name="fin_tuition_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    base_tuition_usd__gt=0,
                ),
                name="fin_tuition_positive",
            ),
        ]

    def __str__(self):
        return (
            f"{self.grade_level} - "
            f"{self.academic_year} - "
            f"{self.base_tuition_usd} USD"
        )


class StudentFinancialAccount(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    enrollment = models.OneToOneField(
        Enrollment,
        on_delete=models.PROTECT,
        related_name="financial_account",
    )

    tuition_plan = models.ForeignKey(
        GradeTuitionPlan,
        on_delete=models.PROTECT,
        related_name="student_accounts",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_financial_accounts",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "finance_student_account"

    def __str__(self):
        return (
            f"{self.enrollment.student} - "
            f"{self.enrollment.academic_year}"
        )


class StudentDiscount(models.Model):
    class DiscountType(models.TextChoices):
        PERCENTAGE = "percentage", "نسبة مئوية"
        FIXED = "fixed", "مبلغ ثابت"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    account = models.ForeignKey(
        StudentFinancialAccount,
        on_delete=models.PROTECT,
        related_name="discounts",
    )

    discount_type = models.CharField(
        max_length=20,
        choices=DiscountType.choices,
    )

    value = models.DecimalField(
        max_digits=18,
        decimal_places=2,
    )

    currency = models.CharField(
        max_length=10,
        choices=MoneyCurrency.choices,
        blank=True,
        default="",
    )

    exchange_rate_syp_per_usd = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
    )

    equivalent_usd = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    reason = models.TextField(
        blank=True,
        default="",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_discounts",
    )

    is_cancelled = models.BooleanField(
        default=False,
    )

    cancellation_reason = models.TextField(
        blank=True,
        default="",
    )

    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cancelled_discounts",
        null=True,
        blank=True,
    )

    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        db_table = "finance_student_discount"

        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    value__gt=0,
                ),
                name="fin_disc_val_pos",
            ),

            models.CheckConstraint(
                condition=(
                    models.Q(
                        discount_type="percentage",
                        value__lte=100,
                        currency="",
                        exchange_rate_syp_per_usd__isnull=True,
                        equivalent_usd__isnull=True,
                    )
                    | models.Q(
                        discount_type="fixed",
                        currency="usd",
                        exchange_rate_syp_per_usd__isnull=True,
                        equivalent_usd=models.F("value"),
                    )
                    | models.Q(
                        discount_type="fixed",
                        currency="syp",
                        exchange_rate_syp_per_usd__gt=0,
                        equivalent_usd__gt=0,
                    )
                ),
                name="fin_disc_type_valid",
            ),

            models.CheckConstraint(
                condition=(
                    models.Q(
                        is_cancelled=False,
                        cancellation_reason="",
                        cancelled_by__isnull=True,
                        cancelled_at__isnull=True,
                    )
                    | (
                        models.Q(
                            is_cancelled=True,
                            cancelled_by__isnull=False,
                            cancelled_at__isnull=False,
                        )
                        & ~models.Q(
                            cancellation_reason="",
                        )
                    )
                ),
                name="fin_disc_cancel_valid",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "account",
                    "is_cancelled",
                ],
                name="fin_disc_acc_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.account} - "
            f"{self.get_discount_type_display()} - "
            f"{self.value}"
        )


class Payment(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    account = models.ForeignKey(
        StudentFinancialAccount,
        on_delete=models.PROTECT,
        related_name="payments",
    )

    currency = models.CharField(
        max_length=10,
        choices=MoneyCurrency.choices,
    )

    amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
    )

    exchange_rate_syp_per_usd = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
    )

    equivalent_usd = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    paid_at = models.DateTimeField(
        default=timezone.now,
    )

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_payments",
    )

    is_cancelled = models.BooleanField(
        default=False,
    )

    cancellation_reason = models.TextField(
        blank=True,
        default="",
    )

    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cancelled_payments",
        null=True,
        blank=True,
    )

    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        db_table = "finance_payment"

        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    amount__gt=0,
                ),
                name="fin_pay_amount_pos",
            ),

            models.CheckConstraint(
                condition=models.Q(
                    equivalent_usd__gt=0,
                ),
                name="fin_pay_usd_pos",
            ),

            models.CheckConstraint(
                condition=(
                    models.Q(
                        currency="usd",
                        exchange_rate_syp_per_usd__isnull=True,
                        equivalent_usd=models.F("amount"),
                    )
                    | models.Q(
                        currency="syp",
                        exchange_rate_syp_per_usd__gt=0,
                    )
                ),
                name="fin_pay_curr_valid",
            ),

            models.CheckConstraint(
                condition=(
                    models.Q(
                        is_cancelled=False,
                        cancellation_reason="",
                        cancelled_by__isnull=True,
                        cancelled_at__isnull=True,
                    )
                    | (
                        models.Q(
                            is_cancelled=True,
                            cancelled_by__isnull=False,
                            cancelled_at__isnull=False,
                        )
                        & ~models.Q(
                            cancellation_reason="",
                        )
                    )
                ),
                name="fin_pay_cancel_valid",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "account",
                    "is_cancelled",
                ],
                name="fin_pay_acc_idx",
            ),

            models.Index(
                fields=[
                    "paid_at",
                ],
                name="fin_pay_date_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.account} - "
            f"{self.amount} {self.currency.upper()}"
        )