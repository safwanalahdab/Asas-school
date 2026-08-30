from .models import Payment, StudentDiscount, StudentFinancialAccount
from .services import calculate_account_totals, calculate_discount_usd


def get_mobile_financial_account(*, enrollment):
    return StudentFinancialAccount.objects.filter(
        enrollment=enrollment,
    ).select_related(
        "enrollment__student",
        "enrollment__academic_year",
        "enrollment__section__grade_level",
        "tuition_plan__academic_year",
        "tuition_plan__grade_level",
    ).first()


def get_mobile_finance_data(*, account):
    totals = calculate_account_totals(account)
    if totals["remaining_usd"] <= 0:
        payment_status = "paid"
    elif totals["total_paid_usd"] > 0:
        payment_status = "partial"
    else:
        payment_status = "unpaid"

    discounts = list(
        StudentDiscount.objects.filter(account=account).order_by("-created_at")
    )
    payments = list(
        Payment.objects.filter(account=account).order_by("-paid_at", "-created_at")
    )
    discount_data = []
    for discount in discounts:
        discount_data.append({
            "id": discount.id,
            "discount_type": discount.discount_type,
            "discount_type_display": discount.get_discount_type_display(),
            "value": discount.value,
            "currency": discount.currency,
            "currency_display": discount.get_currency_display(),
            "exchange_rate_syp_per_usd": discount.exchange_rate_syp_per_usd,
            "equivalent_usd": discount.equivalent_usd,
            "discount_usd": calculate_discount_usd(
                discount,
                base_tuition_usd=totals["base_tuition_usd"],
            ),
            "reason": discount.reason,
            "is_cancelled": discount.is_cancelled,
        })

    return {
        "summary": {
            "currency": "USD",
            **totals,
            "payment_status": payment_status,
        },
        "discounts": discount_data,
        "payments": payments,
    }
