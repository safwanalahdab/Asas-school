from decimal import Decimal

from django.db.models import (
    Case,
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import (
    Coalesce,
    Concat,
    Round,
)
from django_filters import rest_framework as filters

from .models import (
    GradeTuitionPlan,
    Payment,
    StudentDiscount,
    StudentFinancialAccount,
)


ZERO = Decimal("0.00")
HUNDRED = Decimal("100")

MONEY_FIELD = DecimalField(
    max_digits=18,
    decimal_places=2,
)


class GradeTuitionPlanFilter(
    filters.FilterSet
):
    class Meta:
        model = GradeTuitionPlan

        fields = (
            "academic_year",
            "grade_level",
        )


class StudentFinancialAccountFilter(
    filters.FilterSet
):
    class PaymentStatus:
        UNPAID = "unpaid"
        PARTIAL = "partial"
        PAID = "paid"

        CHOICES = (
            (
                UNPAID,
                "غير مدفوع",
            ),
            (
                PARTIAL,
                "مدفوع جزئيًا",
            ),
            (
                PAID,
                "مسدد",
            ),
        )

    academic_year = filters.UUIDFilter(
        field_name="enrollment__academic_year_id",
    )

    grade_level = filters.UUIDFilter(
        field_name="enrollment__section__grade_level_id",
    )

    student = filters.UUIDFilter(
        field_name="enrollment__student_id",
    )

    payment_status = filters.ChoiceFilter(
        choices=PaymentStatus.CHOICES,
        method="filter_payment_status",
    )

    search = filters.CharFilter(
        method="filter_search",
    )

    class Meta:
        model = StudentFinancialAccount
        fields = ()

    def filter_search(
        self,
        queryset,
        name,
        value,
    ):
        value = value.strip()

        if not value:
            return queryset

        queryset = queryset.annotate(
            student_full_name_search=Concat(
                "enrollment__student__first_name",
                Value(" "),
                "enrollment__student__last_name",
            ),
        )

        return queryset.filter(
            Q(
                enrollment__student__first_name__icontains=value
            )
            | Q(
                enrollment__student__last_name__icontains=value
            )
            | Q(
                enrollment__student__father_name__icontains=value
            )
            | Q(
                student_full_name_search__icontains=value
            )
        ).distinct()

    def filter_payment_status(
        self,
        queryset,
        name,
        value,
    ):
        discount_amount_expression = Case(
            When(
                discount_type=StudentDiscount.DiscountType.PERCENTAGE,
                then=Round(
                    ExpressionWrapper(
                        F(
                            "account__tuition_plan__base_tuition_usd"
                        )
                        * F("value")
                        / Value(HUNDRED),
                        output_field=MONEY_FIELD,
                    ),
                    precision=2,
                ),
            ),
            When(
                discount_type=StudentDiscount.DiscountType.FIXED,
                then=F("equivalent_usd"),
            ),
            default=Value(ZERO),
            output_field=MONEY_FIELD,
        )

        discount_total_subquery = (
            StudentDiscount.objects
            .filter(
                account_id=OuterRef("pk"),
                is_cancelled=False,
            )
            .annotate(
                calculated_usd=discount_amount_expression,
            )
            .values(
                "account_id",
            )
            .annotate(
                total_usd=Sum(
                    "calculated_usd",
                ),
            )
            .values(
                "total_usd",
            )[:1]
        )

        payment_total_subquery = (
            Payment.objects
            .filter(
                account_id=OuterRef("pk"),
                is_cancelled=False,
            )
            .values(
                "account_id",
            )
            .annotate(
                total_usd=Sum(
                    "equivalent_usd",
                ),
            )
            .values(
                "total_usd",
            )[:1]
        )

        queryset = queryset.annotate(
            finance_filter_discounts_usd=Coalesce(
                Subquery(
                    discount_total_subquery,
                    output_field=MONEY_FIELD,
                ),
                Value(ZERO),
                output_field=MONEY_FIELD,
            ),
            finance_filter_paid_usd=Coalesce(
                Subquery(
                    payment_total_subquery,
                    output_field=MONEY_FIELD,
                ),
                Value(ZERO),
                output_field=MONEY_FIELD,
            ),
        )

        queryset = queryset.annotate(
            finance_filter_remaining_usd=ExpressionWrapper(
                F("tuition_plan__base_tuition_usd")
                - F("finance_filter_discounts_usd")
                - F("finance_filter_paid_usd"),
                output_field=MONEY_FIELD,
            )
        )

        if value == self.PaymentStatus.UNPAID:
            return queryset.filter(
                finance_filter_paid_usd__lte=ZERO,
                finance_filter_remaining_usd__gt=ZERO,
            )

        if value == self.PaymentStatus.PARTIAL:
            return queryset.filter(
                finance_filter_paid_usd__gt=ZERO,
                finance_filter_remaining_usd__gt=ZERO,
            )

        if value == self.PaymentStatus.PAID:
            return queryset.filter(
                finance_filter_remaining_usd__lte=ZERO,
            )

        return queryset